"""
Генерация btc_snapshot.json и запись в таблицу `snapshots`.
Схема (ai_trading_bot.sql):
- captured_at_utc: DATETIME (UTC)
- price: DECIMAL
- timeframe: VARCHAR(16)
- structure_tag, momentum_tag, atr_5m, session: tags/metrics
- payload_json: longtext (полный снимок)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

# --- bootstrap imports for cron execution ---
CURRENT_FILE = os.path.abspath(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_FILE)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection

SYMBOL_DB = "BTCUSDT"
SYMBOL_SNAPSHOT = "BTCUSDT"
SNAPSHOT_TIMEFRAME = "5m"
TIMEFRAMES = ["1m", "5m", "15m", "1h"]

LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "generate_btc_snapshot.log")
SNAPSHOT_PATH = os.path.join(PROJECT_ROOT, "data", "btc_snapshot.json")

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


def fetch_recent_candles(conn, symbol: str, timeframe: str, limit: int = 150) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            open_time,
            close_time,
            open_price  AS open,
            high_price  AS high,
            low_price   AS low,
            close_price AS close,
            volume,
            quote_volume,
            trades_count
        FROM candles
        WHERE symbol=%s AND timeframe=%s
        ORDER BY open_time DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, timeframe, limit))
        rows = cur.fetchall() or []

    candles: List[Dict[str, Any]] = []
    for row in reversed(rows):
        open_dt = row[0]
        close_dt = row[1]
        candles.append(
            {
                "open_time": open_dt.isoformat() if open_dt else None,
                "close_time": close_dt.isoformat() if close_dt else None,
                "open": float(row[2]) if row[2] is not None else None,
                "high": float(row[3]) if row[3] is not None else None,
                "low": float(row[4]) if row[4] is not None else None,
                "close": float(row[5]) if row[5] is not None else None,
                "volume": float(row[6]) if row[6] is not None else None,
                "quote_volume": float(row[7]) if row[7] is not None else None,
                "trades_count": int(row[8]) if row[8] is not None else None,
            }
        )
    return candles


def fetch_last_derivatives(conn, symbol: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT timestamp, open_interest, funding_rate, taker_buy_volume, taker_sell_volume, taker_buy_ratio
        FROM derivatives
        WHERE symbol=%s
        ORDER BY timestamp DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
        if not row:
            return None

    return {
        "timestamp": row[0].isoformat() if row[0] else None,
        "open_interest": float(row[1]) if row[1] is not None else None,
        "funding_rate": float(row[2]) if row[2] is not None else None,
        "taker_buy_volume": float(row[3]) if row[3] is not None else None,
        "taker_sell_volume": float(row[4]) if row[4] is not None else None,
        "taker_buy_ratio": float(row[5]) if row[5] is not None else None,
    }


def compute_structure_tag(candles: List[Dict[str, Any]]) -> str:
    if len(candles) < 2:
        return "unclear"
    last = candles[-1]
    prev = candles[-2]
    if last["close"] > prev["close"]:
        return "bullish"
    if last["close"] < prev["close"]:
        return "bearish"
    return "neutral"


def compute_momentum(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candles:
        return {"tag": "neutral", "score": 0.0}
    closes = [c["close"] for c in candles]
    first = closes[0]
    last = closes[-1]
    drift = (last - first) / first if first else 0.0
    mid = median(closes[-10:]) if len(closes) >= 10 else median(closes)
    distance_from_mid = (last - mid) / mid if mid else 0.0
    score = max(-1.0, min(1.0, drift * 5 + distance_from_mid * 2))
    if drift > 0.002 and distance_from_mid > 0:
        tag = "impulse_up"
    elif drift < -0.002 and distance_from_mid < 0:
        tag = "impulse_down"
    else:
        tag = "neutral"
    return {"tag": tag, "score": round(score, 3)}


def compute_atr(candles: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, period + 1):
        cur = candles[-i]
        prev = candles[-i - 1]
        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def detect_session(now_utc: datetime) -> str:
    hour = now_utc.hour
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 16:
        return "EU"
    return "US"


def build_snapshot(conn) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts_ms = int(now_utc.timestamp() * 1000)
    ts_iso = now_utc.isoformat()

    candles_by_tf: Dict[str, Any] = {}
    last_price: Optional[float] = None
    atr_5m: Optional[float] = None

    for tf in TIMEFRAMES:
        series = fetch_recent_candles(conn, SYMBOL_DB, tf, limit=200)
        if not series:
            continue
        candles_by_tf[tf] = {
            "open_time": series[-1]["open_time"],
            "close_time": series[-1]["close_time"],
            "open": series[-1]["open"],
            "high": series[-1]["high"],
            "low": series[-1]["low"],
            "close": series[-1]["close"],
            "volume": series[-1]["volume"],
        }
        if tf == "1m":
            last_price = series[-1]["close"]
        if tf == "5m":
            atr_val = compute_atr(series)
            atr_5m = round(atr_val, 8) if atr_val is not None else None

    if last_price is None and "5m" in candles_by_tf:
        last_price = candles_by_tf["5m"].get("close")
    if last_price is None:
        raise RuntimeError("No candles available to derive price")

    tf5_series = fetch_recent_candles(conn, SYMBOL_DB, "5m", limit=50)
    structure_tag = compute_structure_tag(tf5_series) if tf5_series else "unclear"
    momentum_block = compute_momentum(tf5_series)

    snapshot: Dict[str, Any] = {
        "symbol": SYMBOL_SNAPSHOT,
        "timestamp": ts_iso,
        "captured_at_utc": ts_iso,
        "timestamp_ms": ts_ms,
        "price": last_price,
        "timeframe": SNAPSHOT_TIMEFRAME,
        "structure": {"tag": structure_tag, "atr": atr_5m},
        "momentum": momentum_block,
        "session": {"current": detect_session(now_utc)},
        "candles": candles_by_tf,
    }

    deriv = fetch_last_derivatives(conn, SYMBOL_DB)
    if deriv:
        snapshot["derivatives"] = deriv

    return snapshot


def persist_snapshot(conn, snapshot: Dict[str, Any], captured_at: datetime) -> int:
    sql = """
        INSERT INTO snapshots (
            symbol,
            captured_at_utc,
            price,
            timeframe,
            structure_tag,
            momentum_tag,
            atr_5m,
            session,
            payload_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            price=VALUES(price),
            structure_tag=VALUES(structure_tag),
            momentum_tag=VALUES(momentum_tag),
            atr_5m=VALUES(atr_5m),
            session=VALUES(session),
            payload_json=VALUES(payload_json)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                snapshot.get("symbol", SYMBOL_DB),
                captured_at,
                snapshot.get("price"),
                snapshot.get("timeframe", SNAPSHOT_TIMEFRAME),
                snapshot.get("structure", {}).get("tag"),
                snapshot.get("momentum", {}).get("tag"),
                snapshot.get("structure", {}).get("atr"),
                snapshot.get("session", {}).get("current"),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid if cur.lastrowid else 0


def save_snapshot_to_file(snapshot: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    tmp_path = SNAPSHOT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SNAPSHOT_PATH)


# --- main ---

def main() -> None:
    setup_logging()
    logger.info("generate_btc_snapshot: started")

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("generate_btc_snapshot: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        snapshot = build_snapshot(conn)
        captured_at = datetime.fromisoformat(snapshot["captured_at_utc"])
        db_id = persist_snapshot(conn, snapshot, captured_at)
        if db_id:
            snapshot["db_id"] = db_id
        save_snapshot_to_file(snapshot)
        logger.info("generate_btc_snapshot: saved snapshot ts=%s db_id=%s", snapshot.get("timestamp"), db_id or "n/a")
    except Exception as e:
        logger.error("generate_btc_snapshot: failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("generate_btc_snapshot: finished")


if __name__ == "__main__":
    main()
