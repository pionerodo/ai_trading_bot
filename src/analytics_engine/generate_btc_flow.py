"""
Генерация btc_flow.json и запись в таблицу `flows`.
Схема flows (ai_trading_bot.sql):
- captured_at_utc DATETIME
- current_price DECIMAL
- etp_net_flow_usd DECIMAL
- crowd_bias_score, trap_index_score, risk_global_score DECIMAL
- warnings_json, liquidation_json, etp_summary_json, payload_json
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection

LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "generate_btc_flow.log")

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "btc_snapshot.json")
ETP_PATH = os.path.join(DATA_DIR, "btc_etp_flow.json")
LIQ_SNAPSHOT_PATH = os.path.join(DATA_DIR, "btc_liq_snapshot.json")
NEWS_PATH = os.path.join(DATA_DIR, "news_sentiment.json")
FLOW_PATH = os.path.join(DATA_DIR, "btc_flow.json")
LIQ_HISTORY_PATH = os.path.join(DATA_DIR, "btc_liq_map.json")

SYMBOL_DB = "BTCUSDT"
MAX_LIQ_HISTORY = 365

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        fh = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        logger.warning("generate_btc_flow: file not found: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("generate_btc_flow: failed to load %s: %s", path, e, exc_info=True)
        return None


def append_liq_history(liq_obj: Dict[str, Any], history_path: str) -> None:
    if not liq_obj:
        return
    ts = liq_obj.get("captured_at_ms") or liq_obj.get("timestamp_ms")
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    entry = dict(liq_obj)
    if entry.get("captured_at_ms") is None and entry.get("timestamp_ms") is None:
        entry["captured_at_ms"] = ts

    history: List[Any]
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, list):
                history = obj
            elif isinstance(obj, dict):
                history = [obj]
            else:
                history = []
        except Exception:
            history = []
    else:
        history = []

    history.append(entry)
    if len(history) > MAX_LIQ_HISTORY:
        history = history[-MAX_LIQ_HISTORY:]

    tmp = history_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    os.replace(tmp, history_path)


def summarize_zones(zones: List[Dict[str, Any]]) -> Dict[str, float]:
    total_long = 0.0
    total_short = 0.0
    for z in zones:
        try:
            side = (z.get("side") or "").lower()
            strength = float(z.get("strength") or 0.0)
        except Exception:
            continue
        if side == "long":
            total_long += strength
        elif side == "short":
            total_short += strength
    return {
        "total_long": total_long,
        "total_short": total_short,
        "imbalance": total_short - total_long,
    }


def analyze_liq_history(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(history) < 2:
        return None
    prev = history[-2]
    last = history[-1]
    zones_prev = prev.get("zones") or []
    zones_last = last.get("zones") or []
    if not isinstance(zones_prev, list):
        zones_prev = []
    if not isinstance(zones_last, list):
        zones_last = []
    summary_prev = summarize_zones(zones_prev)
    summary_last = summarize_zones(zones_last)
    imb_delta = summary_last["imbalance"] - summary_prev["imbalance"]

    current_price = last.get("current_price")
    closest_short_dist = None
    closest_long_dist = None
    try:
        if current_price is not None:
            cp = float(current_price)
            for z in zones_last:
                try:
                    side = (z.get("side") or "").lower()
                    price = float(z.get("price") or 0.0)
                except Exception:
                    continue
                if side == "short" and price > cp:
                    dist = price - cp
                    if closest_short_dist is None or dist < closest_short_dist:
                        closest_short_dist = dist
                elif side == "long" and price < cp:
                    dist = cp - price
                    if closest_long_dist is None or dist < closest_long_dist:
                        closest_long_dist = dist
    except Exception:
        pass

    return {
        "imbalance_delta": imb_delta,
        "closest_short_dist": closest_short_dist,
        "closest_long_dist": closest_long_dist,
    }


def build_etp_summary(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    try:
        inflow = float(data.get("inflow", 0.0))
        outflow = float(data.get("outflow", 0.0))
        net = inflow - outflow
        return {"inflow": inflow, "outflow": outflow, "net": net}
    except Exception:
        return None


def build_liquidation(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    try:
        return {
            "zones": data.get("zones"),
            "warnings": data.get("warnings"),
            "current_price": data.get("current_price"),
        }
    except Exception:
        return None


def build_news(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    try:
        return {
            "sentiment": data.get("sentiment"),
            "score": data.get("score"),
            "headline": data.get("headline"),
        }
    except Exception:
        return None


def compute_flow_score(payload: Dict[str, Any]) -> Optional[float]:
    parts: List[float] = []
    etp = payload.get("etp_summary")
    if etp:
        try:
            net = float(etp.get("net", 0.0))
            if net != 0:
                parts.append(max(-1.0, min(1.0, net / 1000.0)))
        except Exception:
            pass
    news = payload.get("news")
    if news and isinstance(news, dict) and news.get("score") is not None:
        try:
            parts.append(float(news.get("score")))
        except Exception:
            pass
    liq = payload.get("liquidation")
    if liq:
        try:
            zones = liq.get("zones") or []
            imbalance = summarize_zones(zones).get("imbalance", 0.0)
            parts.append(max(-1.0, min(1.0, imbalance / 1_000_000)))
        except Exception:
            pass
    if not parts:
        return None
    try:
        return sum(parts) / len(parts)
    except Exception:
        return None


def insert_flow(conn, payload: Dict[str, Any], ts: datetime) -> int:
    sql = """
        INSERT INTO flows (
            symbol,
            timestamp,
            current_price,
            etp_net_flow_usd,
            crowd_bias_score,
            trap_index_score,
            risk_global_score,
            warnings_json,
            liquidation_json,
            etp_summary_json,
            payload_json
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            current_price=VALUES(current_price),
            etp_net_flow_usd=VALUES(etp_net_flow_usd),
            crowd_bias_score=VALUES(crowd_bias_score),
            trap_index_score=VALUES(trap_index_score),
            risk_global_score=VALUES(risk_global_score),
            warnings_json=VALUES(warnings_json),
            liquidation_json=VALUES(liquidation_json),
            etp_summary_json=VALUES(etp_summary_json),
            payload_json=VALUES(payload_json)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                SYMBOL_DB,
                ts,
                payload.get("price"),
                payload.get("etp_summary", {}).get("net"),
                payload.get("flow_score"),
                payload.get("trap_index_score"),
                payload.get("flow_score"),
                json.dumps(payload.get("warnings"), ensure_ascii=False) if payload.get("warnings") else None,
                json.dumps(payload.get("liquidation"), ensure_ascii=False) if payload.get("liquidation") else None,
                json.dumps(payload.get("etp_summary"), ensure_ascii=False) if payload.get("etp_summary") else None,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid if cur.lastrowid else 0


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def upsert_market_flow(conn, flow: Dict[str, Any], ts: datetime) -> None:
    timestamp_ms = flow.get("timestamp_ms")
    if timestamp_ms is None:
        try:
            timestamp_ms = int(ts.timestamp() * 1000)
        except Exception:
            timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    symbol = flow.get("symbol") or SYMBOL_DB

    price_block = flow.get("price")
    current_price = None
    if isinstance(price_block, dict):
        for key in ("current", "last", "value"):
            if price_block.get(key) is not None:
                current_price = _safe_float(price_block.get(key))
                break
    else:
        current_price = _safe_float(price_block)

    crowd_sentiment = _safe_float(flow.get("flow_score"))
    funding_rate = _safe_float(flow.get("funding_rate"))
    open_interest_change = _safe_float(flow.get("open_interest_change"))

    liquidation_block = flow.get("liquidation") if isinstance(flow.get("liquidation"), dict) else {}
    liquidations_long = _safe_int(liquidation_block.get("liquidations_long")) if liquidation_block else None
    liquidations_short = _safe_int(liquidation_block.get("liquidations_short")) if liquidation_block else None

    risk_score = _safe_float(flow.get("risk_score") or flow.get("flow_score"))

    select_sql = "SELECT id FROM market_flow WHERE symbol=%s AND timestamp_ms=%s"
    insert_sql = """
        INSERT INTO market_flow (
            timestamp_ms,
            symbol,
            crowd_sentiment,
            funding_rate,
            open_interest_change,
            liquidations_long,
            liquidations_short,
            risk_score,
            json_data,
            current_price
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    update_sql = """
        UPDATE market_flow
        SET
            crowd_sentiment=%s,
            funding_rate=%s,
            open_interest_change=%s,
            liquidations_long=%s,
            liquidations_short=%s,
            risk_score=%s,
            json_data=%s,
            current_price=%s
        WHERE id=%s
    """

    with conn.cursor() as cur:
        cur.execute(select_sql, (symbol, timestamp_ms))
        row = cur.fetchone()
        if row:
            cur.execute(
                update_sql,
                (
                    crowd_sentiment,
                    funding_rate,
                    open_interest_change,
                    liquidations_long,
                    liquidations_short,
                    risk_score,
                    json.dumps(flow, ensure_ascii=False),
                    current_price,
                    row[0],
                ),
            )
        else:
            cur.execute(
                insert_sql,
                (
                    timestamp_ms,
                    symbol,
                    crowd_sentiment,
                    funding_rate,
                    open_interest_change,
                    liquidations_long,
                    liquidations_short,
                    risk_score,
                    json.dumps(flow, ensure_ascii=False),
                    current_price,
                ),
            )
        conn.commit()


def main() -> None:
    setup_logging()
    logger.info("generate_btc_flow: started")

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("generate_btc_flow: DB connection error: %s", e, exc_info=True)
        return

    snapshot = load_json(SNAPSHOT_PATH)
    etp = load_json(ETP_PATH)
    liq = load_json(LIQ_SNAPSHOT_PATH)
    news = load_json(NEWS_PATH)

    if not snapshot:
        logger.error("generate_btc_flow: missing snapshot; aborting")
        return

    ts_str = snapshot.get("captured_at_utc") or snapshot.get("timestamp")
    if not ts_str:
        logger.error("generate_btc_flow: snapshot missing timestamp; aborting")
        return

    try:
        ts = datetime.fromisoformat(ts_str)
    except Exception as e:
        logger.error("generate_btc_flow: invalid timestamp: %s", e, exc_info=True)
        return

    payload: Dict[str, Any] = {
        "symbol": snapshot.get("symbol"),
        "timestamp": ts_str,
        "price": snapshot.get("price"),
        "etp_summary": build_etp_summary(etp),
        "liquidation": build_liquidation(liq),
        "news": build_news(news),
        "warnings": {},
    }

    append_liq_history(payload.get("liquidation") or {}, LIQ_HISTORY_PATH)
    flow_score = compute_flow_score(payload)
    payload["flow_score"] = flow_score

    liq_history = load_json(LIQ_HISTORY_PATH)
    liq_context = analyze_liq_history(liq_history if isinstance(liq_history, list) else [])
    if liq_context:
        payload["trap_index_score"] = liq_context.get("imbalance_delta")

    warnings: Dict[str, Any] = {}
    if payload.get("etp_summary") and abs(payload["etp_summary"].get("net", 0)) > 2000:
        warnings["etf_warning"] = True
    if payload.get("liquidation", {}).get("warnings"):
        warnings["liquidation_warning"] = True

    news_block = payload.get("news")
    news_sentiment = None
    if news_block and isinstance(news_block, dict):
        news_sentiment = news_block.get("sentiment")

    if news_sentiment == "bearish":
        warnings["news_warning"] = True

    payload["warnings"] = warnings

    try:
        payload["timestamp_ms"] = int(ts.timestamp() * 1000)
        db_id = insert_flow(conn, payload, ts)
        if db_id:
            payload["db_id"] = db_id
        upsert_market_flow(conn, payload, ts)
        with open(FLOW_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(FLOW_PATH + ".tmp", FLOW_PATH)
        logger.info("generate_btc_flow: saved flow ts=%s db_id=%s", ts_str, db_id or "n/a")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("generate_btc_flow: finished")


if __name__ == "__main__":
    main()
