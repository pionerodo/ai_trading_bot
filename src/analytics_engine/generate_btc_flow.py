"""
Генерация btc_flow.json и запись в таблицу `flows`.
Использует btc_snapshot.json, btc_etp_flow.json, btc_liq_snapshot.json,
news_sentiment.json и формирует агрегированный контекст по спецификации
DATA_PIPELINE.md.
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
_market_flow_checked = False
_market_flow_exists = False


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# История ликвидаций: btc_liq_map.json
# ---------------------------------------------------------------------------

def append_liq_history(liq_obj: Dict[str, Any], history_path: str) -> None:
    if not liq_obj:
        return

    ts = liq_obj.get("captured_at_ms") or liq_obj.get("timestamp_ms")
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    entry = dict(liq_obj)
    if entry.get("captured_at_ms") is None and entry.get("timestamp_ms") is None:
        entry["captured_at_ms"] = ts

    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, list):
                history: List[Any] = obj
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


def load_liq_history(history_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        elif isinstance(obj, dict):
            return [obj]
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Вспомогательные функции по ликвидациям
# ---------------------------------------------------------------------------

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

    imb_prev = summary_prev["imbalance"]
    imb_last = summary_last["imbalance"]
    imb_delta = imb_last - imb_prev

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

    def zones_to_map(zs: List[Dict[str, Any]]) -> Dict[Tuple[str, float], float]:
        m: Dict[Tuple[str, float], float] = {}
        for z in zs:
            try:
                side = (z.get("side") or "").lower()
                price = float(z.get("price") or 0.0)
                strength = float(z.get("strength") or 0.0)
            except Exception:
                continue
            key = (side, price)
            m[key] = m.get(key, 0.0) + strength
        return m

    prev_map = zones_to_map(zones_prev)
    last_map = zones_to_map(zones_last)

    changed: List[Dict[str, Any]] = []
    new_zones: List[Dict[str, Any]] = []
    disappeared_zones: List[Dict[str, Any]] = []

    for key, prev_strength in prev_map.items():
        last_strength = last_map.get(key)
        side, price = key
        if last_strength is not None:
            delta = last_strength - prev_strength
            if abs(delta) > 0:
                changed.append(
                    {
                        "side": side,
                        "price": price,
                        "prev_strength": prev_strength,
                        "last_strength": last_strength,
                        "delta_strength": delta,
                    }
                )
        else:
            disappeared_zones.append(
                {
                    "side": side,
                    "price": price,
                    "prev_strength": prev_strength,
                }
            )

    for key, last_strength in last_map.items():
        if key not in prev_map:
            side, price = key
            new_zones.append({"side": side, "price": price, "last_strength": last_strength})

    changed_sorted = sorted(
        changed,
        key=lambda x: abs(x.get("delta_strength", 0.0)),
        reverse=True,
    )
    top_changed = changed_sorted[:5]

    metrics: Dict[str, Any] = {
        "summary_prev": summary_prev,
        "summary_last": summary_last,
        "imbalance_prev": imb_prev,
        "imbalance_last": imb_last,
        "imbalance_delta": imb_delta,
        "closest_short_distance": closest_short_dist,
        "closest_long_distance": closest_long_dist,
        "top_changed_zones": top_changed,
        "new_zones": new_zones[:5],
        "disappeared_zones": disappeared_zones[:5],
    }

    return metrics


# ---------------------------------------------------------------------------
# Crowd / Risk
# ---------------------------------------------------------------------------

def build_crowd_and_risk(
    snapshot: Dict[str, Any],
    etp: Optional[Dict[str, Any]],
    news: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    warnings: List[Dict[str, Any]] = []

    crowd_bias = "neutral"
    crowd_score = 0.5
    crowd_desc_parts: List[str] = []

    if etp and isinstance(etp.get("summary"), dict):
        etp_signal = etp["summary"].get("signal")
        if etp_signal == "bullish":
            crowd_score += 0.1
            crowd_desc_parts.append("ETF-flows mildly bullish")
        elif etp_signal == "bearish":
            crowd_score -= 0.1
            crowd_desc_parts.append("ETF-flows mildly bearish")

    if news:
        news_label = news.get("label")
        if news_label == "bullish":
            crowd_score += 0.1
            crowd_desc_parts.append("News sentiment bullish")
        elif news_label == "bearish":
            crowd_score -= 0.1
            crowd_desc_parts.append("News sentiment bearish")

    crowd_score = max(0.0, min(1.0, crowd_score))

    if crowd_score > 0.55:
        crowd_bias = "bullish"
    elif crowd_score < 0.45:
        crowd_bias = "bearish"
    else:
        crowd_bias = "neutral"

    risk_global = 0.5 + (crowd_score - 0.5) * 0.3
    risk_global = max(0.0, min(1.0, risk_global))

    if risk_global < 0.25:
        risk_mode = "risk_off"
    elif risk_global < 0.5:
        risk_mode = "neutral"
    elif risk_global < 0.75:
        risk_mode = "cautious_risk_on"
    else:
        risk_mode = "aggressive_risk_on"

    if not etp:
        warnings.append(
            {
                "type": "missing_etp",
                "level": "info",
                "message": "btc_etp_flow.json missing or invalid; ETF influence not applied",
            }
        )
    if not news:
        warnings.append(
            {
                "type": "missing_news_sentiment",
                "level": "info",
                "message": "news_sentiment.json missing or invalid; news influence not applied",
            }
        )

    crowd_block: Dict[str, Any] = {
        "bias": crowd_bias,
        "score": crowd_score,
        "description": "; ".join(crowd_desc_parts) if crowd_desc_parts else "",
        "fomo": 0.0,
        "fud": 0.0,
    }

    trap_index_block: Dict[str, Any] = {
        "score": 0.0,
        "side": "none",
        "comment": "",
    }

    risk_block: Dict[str, Any] = {
        "global_score": round(risk_global, 3),
        "mode": risk_mode,
    }

    return crowd_block, trap_index_block, risk_block, warnings


# ---------------------------------------------------------------------------
# market_flow DB (опционально)
# ---------------------------------------------------------------------------

def _check_market_flow_table(conn) -> bool:
    global _market_flow_checked, _market_flow_exists
    if _market_flow_checked:
        return _market_flow_exists
    _market_flow_checked = True
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'market_flow'")
            _market_flow_exists = cur.fetchone() is not None
    except Exception:
        _market_flow_exists = False
    return _market_flow_exists


def upsert_flow_row(conn, flow: Dict[str, Any]) -> None:
    ts_value = flow.get("timestamp_iso") or flow.get("timestamp_ms")
    if not ts_value:
        raise ValueError("upsert_flow_row: timestamp missing")
    ts_dt = (
        datetime.fromtimestamp(flow["timestamp_ms"] / 1000, tz=timezone.utc)
        if flow.get("timestamp_ms")
        else datetime.fromisoformat(str(ts_value).replace("Z", "+00:00"))
    )

    sql = """
        INSERT INTO flows (
            symbol,
            timestamp,
            derivatives_json,
            etp_summary_json,
            liquidation_json,
            crowd_json,
            trap_index_json,
            news_sentiment_json,
            warnings_json,
            risk_global_score,
            risk_mode
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            derivatives_json=VALUES(derivatives_json),
            etp_summary_json=VALUES(etp_summary_json),
            liquidation_json=VALUES(liquidation_json),
            crowd_json=VALUES(crowd_json),
            trap_index_json=VALUES(trap_index_json),
            news_sentiment_json=VALUES(news_sentiment_json),
            warnings_json=VALUES(warnings_json),
            risk_global_score=VALUES(risk_global_score),
            risk_mode=VALUES(risk_mode)
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                flow.get("symbol", SYMBOL_DB),
                ts_dt,
                json.dumps(flow.get("derivatives"), ensure_ascii=False),
                json.dumps(flow.get("etp_summary"), ensure_ascii=False),
                json.dumps(flow.get("liquidation_zones"), ensure_ascii=False),
                json.dumps(flow.get("crowd"), ensure_ascii=False),
                json.dumps(flow.get("trap_index"), ensure_ascii=False),
                json.dumps(flow.get("news_sentiment"), ensure_ascii=False),
                json.dumps(flow.get("warnings"), ensure_ascii=False),
                (flow.get("risk") or {}).get("global_score"),
                (flow.get("risk") or {}).get("mode"),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Формирование btc_flow
# ---------------------------------------------------------------------------

def build_btc_flow(
    snapshot: Dict[str, Any],
    etp: Optional[Dict[str, Any]],
    liq: Optional[Dict[str, Any]],
    news: Optional[Dict[str, Any]],
    liq_metrics: Optional[Dict[str, Any]],
    warnings_extra: List[Dict[str, Any]],
) -> Dict[str, Any]:
    timestamp_iso = snapshot.get("timestamp_iso")
    timestamp_ms = snapshot.get("timestamp_ms")
    price = snapshot.get("price")

    derivatives_block = snapshot.get("derivatives", {})

    etp_summary = None
    if etp and isinstance(etp.get("summary"), dict):
        etp_summary = etp.get("summary")

    liq_block = None
    if liq:
        liq_block = {
            "source": liq.get("source"),
            "current_price": liq.get("current_price"),
            "zones": liq.get("zones") or [],
            "summary": liq.get("summary"),
        }

    crowd_block, trap_index_block, risk_block, warnings_list = build_crowd_and_risk(
        snapshot=snapshot,
        etp=etp,
        news=news,
    )

    warnings_list.extend(warnings_extra)

    flow: Dict[str, Any] = {
        "symbol": SYMBOL_DB,
        "timestamp_iso": timestamp_iso,
        "timestamp_ms": timestamp_ms,
        "price": price,
        "derivatives": derivatives_block,
        "etp_summary": etp_summary,
        "liquidation_zones": liq_block,
        "news_sentiment": news,
        "crowd": crowd_block,
        "trap_index": trap_index_block,
        "warnings": warnings_list,
        "risk": risk_block,
    }

    if liq_metrics is not None:
        flow["liq_metrics"] = liq_metrics

    return flow


def save_flow_to_file(flow: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = FLOW_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(flow, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, FLOW_PATH)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    logger.info("generate_btc_flow: started")

    snapshot = load_json(SNAPSHOT_PATH)
    if not snapshot:
        logger.error("generate_btc_flow: btc_snapshot.json not found or invalid, abort")
        sys.exit(1)

    etp = load_json(ETP_PATH)
    liq_snapshot = load_json(LIQ_SNAPSHOT_PATH)
    news = load_json(NEWS_PATH)

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("generate_btc_flow: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        if liq_snapshot:
            append_liq_history(liq_snapshot, LIQ_HISTORY_PATH)

        liq_metrics = None
        extra_warnings: List[Dict[str, Any]] = []
        history = load_liq_history(LIQ_HISTORY_PATH)
        if history:
            liq_metrics = analyze_liq_history(history)
            if liq_metrics is not None:
                imb_delta = liq_metrics.get("imbalance_delta")
                imb_last = liq_metrics.get("imbalance_last")
                if imb_last is not None and imb_delta is not None:
                    try:
                        imb_last_f = float(imb_last)
                        imb_delta_f = float(imb_delta)
                        if imb_last_f > 0 and imb_delta_f > 0:
                            extra_warnings.append(
                                {
                                    "type": "liq_short_pressure_up",
                                    "level": "info",
                                    "message": "Short-side liquidity above price is growing (squeeze risk up).",
                                }
                            )
                        elif imb_last_f < 0 and imb_delta_f < 0:
                            extra_warnings.append(
                                {
                                    "type": "liq_long_pressure_up",
                                    "level": "info",
                                    "message": "Long-side liquidity below price is growing (downside sweep risk up).",
                                }
                            )
                    except Exception:
                        pass

        flow = build_btc_flow(snapshot, etp, liq_snapshot, news, liq_metrics, extra_warnings)
        save_flow_to_file(flow)
        upsert_flow_row(conn, flow)

        if _check_market_flow_table(conn):
            # минимальный апдейт исторической таблицы, если она присутствует
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO market_flow (timestamp_ms, symbol, json_data)
                        VALUES (%s,%s,%s)
                        ON DUPLICATE KEY UPDATE json_data=VALUES(json_data)
                        """,
                        (
                            flow.get("timestamp_ms"),
                            flow.get("symbol", SYMBOL_DB),
                            json.dumps(flow, ensure_ascii=False),
                        ),
                    )
                conn.commit()
            except Exception:
                logger.warning("generate_btc_flow: market_flow table exists but insert failed", exc_info=True)

        logger.info(
            "generate_btc_flow: saved flow to %s and upserted into flows (ts=%s)",
            FLOW_PATH,
            flow.get("timestamp_iso"),
        )
    except Exception as e:
        logger.error("generate_btc_flow: failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("generate_btc_flow: finished")


if __name__ == "__main__":
    main()
