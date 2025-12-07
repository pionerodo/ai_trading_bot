"""
Генерация btc_snapshot.json и запись в таблицу `snapshots`.
Соответствует DATA_PIPELINE.md и DATABASE_SCHEMA.md: каждые 5 минут
строит компактный снимок рынка BTCUSDT, сохраняет его в data/btc_snapshot.json
и в БД.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection

# --- Настройки ---

SYMBOL_DB = "BTCUSDT"
SYMBOL_SNAPSHOT = "BTCUSDT"

TIMEFRAMES = ["1m", "5m", "15m", "1h"]

LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "generate_btc_snapshot.log")
SNAPSHOT_PATH = os.path.join(PROJECT_ROOT, "data", "btc_snapshot.json")

logger = logging.getLogger(__name__)


# --- Логирование ---

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


# --- DB helpers ---

def fetch_recent_candles(
    conn,
    symbol: str,
    timeframe: str,
    limit: int = 120,
) -> List[Dict[str, Any]]:
    sql = """
        SELECT open_time, open_price, high_price, low_price, close_price, volume
        FROM candles
        WHERE symbol = %s AND timeframe = %s
        ORDER BY open_time DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, timeframe, limit))
        rows = cur.fetchall() or []

    candles: List[Dict[str, Any]] = []
    for row in reversed(rows):
        open_time = row[0]
        candles.append(
            {
                "open_time": int(open_time.timestamp() * 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return candles


def fetch_last_derivatives(conn, symbol: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT timestamp,
               open_interest,
               funding_rate,
               extra_json
        FROM derivatives
        WHERE symbol = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
        if not row:
            return None

        extra = None
        try:
            extra = json.loads(row[3]) if row[3] is not None else None
        except Exception:
            extra = None

        return {
            "timestamp": row[0],
            "open_interest": float(row[1]) if row[1] is not None else None,
            "funding_rate": float(row[2]) if row[2] is not None else None,
            "extra": extra or {},
        }


def persist_snapshot(conn, snapshot: Dict[str, Any]) -> None:
    ts_iso = snapshot.get("timestamp_iso")
    if not ts_iso:
        raise ValueError("persist_snapshot: timestamp_iso missing")
    ts_dt = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))

    candles_block = snapshot.get("candles") or {}
    tf5 = candles_block.get("tf_5m", {})

    sql = """
        INSERT INTO snapshots (
            symbol,
            timestamp,
            price,
            o_5m,
            h_5m,
            l_5m,
            c_5m,
            candles_json,
            market_structure_json,
            momentum_json,
            session_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            price=VALUES(price),
            o_5m=VALUES(o_5m),
            h_5m=VALUES(h_5m),
            l_5m=VALUES(l_5m),
            c_5m=VALUES(c_5m),
            candles_json=VALUES(candles_json),
            market_structure_json=VALUES(market_structure_json),
            momentum_json=VALUES(momentum_json),
            session_json=VALUES(session_json)
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                snapshot.get("symbol", SYMBOL_DB),
                ts_dt,
                snapshot.get("price"),
                tf5.get("o"),
                tf5.get("h"),
                tf5.get("l"),
                tf5.get("c"),
                json.dumps(candles_block, ensure_ascii=False),
                json.dumps(snapshot.get("market_structure", {}), ensure_ascii=False),
                json.dumps(snapshot.get("momentum", {}), ensure_ascii=False),
                json.dumps(snapshot.get("session", {}), ensure_ascii=False),
            ),
        )
    conn.commit()


# --- Вспомогательные вычисления ---

def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def compute_market_structure(candles: List[Dict[str, Any]]) -> str:
    if len(candles) < 3:
        return "unclear"

    last = candles[-1]
    prev = candles[-2]

    higher_high = last["high"] > prev["high"]
    higher_low = last["low"] > prev["low"]
    lower_high = last["high"] < prev["high"]
    lower_low = last["low"] < prev["low"]

    if higher_high and higher_low:
        return "HH-HL"
    if lower_high and lower_low:
        return "LL-LH"
    return "range"


def compute_momentum(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candles:
        return {"state": "neutral", "score": 0.0}

    closes = [c["close"] for c in candles]
    if len(closes) < 3:
        return {"state": "neutral", "score": 0.0}

    last = closes[-1]
    first = closes[0]
    mid = median(closes[-10:]) if len(closes) >= 10 else median(closes)

    drift = (last - first) / first if first else 0.0
    distance_from_mid = (last - mid) / mid if mid else 0.0

    raw_score = _clamp(0.5 + (drift * 5.0) + (distance_from_mid * 2.5))

    if drift > 0.003 and distance_from_mid > 0:
        state = "impulse_up"
    elif drift < -0.003 and distance_from_mid < 0:
        state = "impulse_down"
    elif abs(drift) > 0.0015:
        state = "fading"
    else:
        state = "neutral"

    return {"state": state, "score": round(raw_score, 3)}


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


def detect_session(now_utc: datetime, volatility_regime: str) -> Dict[str, Any]:
    hour = now_utc.hour
    if 0 <= hour < 8:
        current = "Asia"
    elif 8 <= hour < 16:
        current = "EU"
    else:
        current = "US"

    return {
        "current": current,
        "time_utc": now_utc.strftime("%H:%M"),
        "volatility_regime": volatility_regime,
    }


# --- Формирование snapshot ---

def build_btc_snapshot(conn) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_ms = int(now_utc.timestamp() * 1000)
    timestamp_iso = now_utc.isoformat().replace("+00:00", "Z")

    candles_block: Dict[str, Any] = {}
    atr_block: Dict[str, Any] = {}
    structure_block: Dict[str, Any] = {}
    momentum_block: Dict[str, Any] = {}
    last_price: Optional[float] = None

    for tf in TIMEFRAMES:
        series = fetch_recent_candles(conn, SYMBOL_DB, tf, limit=150)
        if not series:
            logger.warning("No candle for %s / %s", SYMBOL_DB, tf)
            continue

        last_candle = series[-1]
        key = f"tf_{tf}"
        candles_block[key] = {
            "o": last_candle["open"],
            "h": last_candle["high"],
            "l": last_candle["low"],
            "c": last_candle["close"],
            "v": last_candle["volume"],
        }

        structure_block[key] = compute_market_structure(series)
        momentum_block[key] = compute_momentum(series)

        atr_value = compute_atr(series)
        if atr_value:
            atr_pct = atr_value / last_candle["close"] if last_candle["close"] else None
            atr_block[key] = {
                "atr": round(atr_value, 2),
                "atr_pct": round(atr_pct, 5) if atr_pct is not None else None,
            }

        if tf == "1m":
            last_price = last_candle["close"]

    if last_price is None:
        if candles_block:
            any_tf = next(iter(candles_block.values()))
            last_price = any_tf["c"]
        else:
            raise RuntimeError("build_btc_snapshot: no candles found at all")

    deriv = fetch_last_derivatives(conn, SYMBOL_DB)
    derivatives_block: Dict[str, Any] = {
        "oi": {
            "value": deriv["open_interest"] if deriv else None,
            "change_24h": None,
        },
        "funding": {
            "current": deriv["funding_rate"] if deriv else None,
            "avg_24h": None,
        },
    }
    if deriv and deriv.get("extra"):
        derivatives_block["extra"] = deriv["extra"]

    def _vol_regime() -> str:
        atr_pct_candidates = [v.get("atr_pct") for v in atr_block.values() if v.get("atr_pct")]
        if not atr_pct_candidates:
            return "unknown"
        latest = atr_pct_candidates[-1]
        if latest < 0.004:
            return "low"
        if latest < 0.01:
            return "normal"
        return "high"

    session_block = detect_session(now_utc, _vol_regime())

    snapshot: Dict[str, Any] = {
        "symbol": SYMBOL_SNAPSHOT,
        "timestamp_iso": timestamp_iso,
        "timestamp_ms": now_ms,
        "price": last_price,
        "candles": candles_block,
        "market_structure": structure_block,
        "momentum": momentum_block,
        "session": session_block,
        "derivatives": derivatives_block,
        "volatility": {"atr": atr_block},
    }

    return snapshot


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
        snapshot = build_btc_snapshot(conn)
        save_snapshot_to_file(snapshot)
        persist_snapshot(conn, snapshot)
        logger.info(
            "generate_btc_snapshot: saved snapshot to %s and DB (ts=%s)",
            SNAPSHOT_PATH,
            snapshot.get("timestamp_iso"),
        )
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
