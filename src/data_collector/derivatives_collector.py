"""
Собираем derivatives-срез для BTCUSDT и пишем в таблицу `derivatives`.
Целевая схема (DATABASE_SCHEMA.md / актуальная MariaDB):
- timestamp: DATETIME (UTC, naive)
- open_interest, funding_rate, taker_buy_volume, taker_sell_volume, taker_buy_ratio,
  basis, basis_pct, cvd_1h, cvd_4h, extra_json
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import urllib.parse
import urllib.request

# --- Ensure project root on sys.path for cron execution ---
CURRENT_FILE = os.path.abspath(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_FILE)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection

# === НАСТРОЙКИ ===

SYMBOL = "BTCUSDT"

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "derivatives_collector.log")


# === ЛОГИРОВАНИЕ ===

def setup_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%%Y-%%m-%%d %%H:%%M:%%S",
    )

    logger_root = logging.getLogger()
    logger_root.setLevel(logging.INFO)

    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(formatter)
        logger_root.addHandler(fh)
    except Exception:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger_root.addHandler(sh)


logger = logging.getLogger(__name__)


# === HTTP ===

def http_get(url: str, params: Dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data)


# === FETCH ФУНКЦИИ ===

def fetch_open_interest(symbol: str) -> Optional[float]:
    url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/openInterest"
    data = http_get(url, {"symbol": symbol})
    try:
        return float(data.get("openInterest"))
    except Exception:
        return None


def fetch_funding_rate(symbol: str) -> Optional[float]:
    url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/premiumIndex"
    data = http_get(url, {"symbol": symbol})
    try:
        return float(data.get("lastFundingRate"))
    except Exception:
        return None


def fetch_taker_stats(symbol: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    url = f"{BINANCE_FUTURES_BASE_URL}/futures/data/takerlongshortRatio"
    params = {
        "symbol": symbol,
        "period": "5m",
        "limit": 1,
    }

    try:
        data = http_get(url, params)
    except Exception as e:
        logger.warning("derivatives: error fetching taker stats: %s", e)
        return None, None, None

    if not isinstance(data, list) or not data:
        return None, None, None

    row = data[-1]
    buy_vol = None
    sell_vol = None
    ratio = None

    try:
        if "buyVol" in row:
            buy_vol = float(row["buyVol"])
        if "sellVol" in row:
            sell_vol = float(row["sellVol"])
        if "buySellRatio" in row:
            ratio = float(row["buySellRatio"])
        elif "longShortRatio" in row:
            ratio = float(row["longShortRatio"])
    except Exception:
        pass

    return buy_vol, sell_vol, ratio


# === DB ===

def _latest_timestamp(conn, symbol: str) -> Optional[datetime]:
    sql = """
        SELECT MAX(timestamp) AS ts
        FROM derivatives
        WHERE symbol = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return row[0]


def insert_derivatives_snapshot(
    conn,
    symbol: str,
    ts: datetime,
    open_interest: Optional[float],
    funding_rate: Optional[float],
    taker_buy_volume: Optional[float],
    taker_sell_volume: Optional[float],
    taker_buy_ratio: Optional[float],
) -> None:
    sql = """
        INSERT INTO derivatives (
            symbol,
            timestamp,
            open_interest,
            funding_rate,
            taker_buy_volume,
            taker_sell_volume,
            taker_buy_ratio,
            basis,
            basis_pct,
            cvd_1h,
            cvd_4h,
            extra_json
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            open_interest=VALUES(open_interest),
            funding_rate=VALUES(funding_rate),
            taker_buy_volume=VALUES(taker_buy_volume),
            taker_sell_volume=VALUES(taker_sell_volume),
            taker_buy_ratio=VALUES(taker_buy_ratio),
            basis=VALUES(basis),
            basis_pct=VALUES(basis_pct),
            cvd_1h=VALUES(cvd_1h),
            cvd_4h=VALUES(cvd_4h),
            extra_json=VALUES(extra_json)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                symbol,
                ts,
                open_interest,
                funding_rate,
                taker_buy_volume,
                taker_sell_volume,
                taker_buy_ratio,
                None,
                None,
                None,
                None,
                None,
            ),
        )
    conn.commit()


# === MAIN ===

def main() -> None:
    setup_logging()
    logger.info("derivatives_collector: started")

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("derivatives_collector: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        now_utc = datetime.utcnow().replace(second=0, microsecond=0)

        last_ts = _latest_timestamp(conn, SYMBOL)
        if last_ts is not None and now_utc <= last_ts:
            logger.info(
                "derivatives[%s]: already up to date (ts=%s, last_ts=%s)",
                SYMBOL,
                now_utc,
                last_ts,
            )
            return

        oi = None
        funding = None
        buy_vol = None
        sell_vol = None
        ratio = None

        try:
            oi = fetch_open_interest(SYMBOL)
        except Exception as e:
            logger.error("derivatives[%s]: error fetching open interest: %s", SYMBOL, e, exc_info=True)

        try:
            funding = fetch_funding_rate(SYMBOL)
        except Exception as e:
            logger.error("derivatives[%s]: error fetching funding: %s", SYMBOL, e, exc_info=True)

        buy_vol, sell_vol, ratio = fetch_taker_stats(SYMBOL)

        insert_derivatives_snapshot(
            conn,
            SYMBOL,
            now_utc,
            oi,
            funding,
            buy_vol,
            sell_vol,
            ratio,
        )

        logger.info(
            "derivatives[%s]: inserted snapshot ts=%s (oi=%s, funding=%s, buy_vol=%s, sell_vol=%s, ratio=%s)",
            SYMBOL,
            now_utc,
            oi,
            funding,
            buy_vol,
            sell_vol,
            ratio,
        )

    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("derivatives_collector: finished")


if __name__ == "__main__":
    main()
