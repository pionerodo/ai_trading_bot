#!/usr/bin/env python3
"""
derivatives_collector.py

Задача:
- регулярно подтягивать деривативные данные с Binance Futures (BTCUSDT)
- писать их в таблицу `derivatives` (MariaDB)
- работать идемпотентно: один срез в минуту, без дублей

Собираем:
- open_interest
- funding_rate
- taker_buy_volume / taker_sell_volume / taker_buy_ratio (если API ответил)
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List

import urllib.request
import urllib.parse

try:
    from .db_utils import get_db_connection  # запуск как модуль
except ImportError:
    from db_utils import get_db_connection  # запуск напрямую

# === НАСТРОЙКИ ===

SYMBOL = "BTCUSDT"

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

LOG_FILE = "logs/derivatives_collector.log"


# === ЛОГИРОВАНИЕ ===

def setup_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Пытаемся писать в файл, если нет — в stdout
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


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
    """
    /fapi/v1/openInterest
    """
    url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/openInterest"
    data = http_get(url, {"symbol": symbol})
    try:
        return float(data.get("openInterest"))
    except Exception:
        return None


def fetch_funding_rate(symbol: str) -> Optional[float]:
    """
    /fapi/v1/premiumIndex
    """
    url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/premiumIndex"
    data = http_get(url, {"symbol": symbol})
    try:
        # lastFundingRate строкой, переводим в float
        return float(data.get("lastFundingRate"))
    except Exception:
        return None


def fetch_taker_stats(symbol: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    /futures/data/takerlongshortRatio
    Берём последний интервал 5m (buyVol / sellVol / buySellRatio).

    Если эндпоинт или структура поменяются, просто вернём None.
    """
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
        # бывает поле buySellRatio или longShortRatio — пробуем оба
        if "buySellRatio" in row:
            ratio = float(row["buySellRatio"])
        elif "longShortRatio" in row:
            ratio = float(row["longShortRatio"])
    except Exception:
        # если что-то не так — просто оставляем None
        pass

    return buy_vol, sell_vol, ratio


# === DB ===

def get_latest_timestamp_ms(conn, symbol: str) -> Optional[int]:
    """
    MAX(timestamp_ms) для символа в derivatives.
    Нужен, чтобы избежать дублей по времени.
    """
    sql = """
        SELECT MAX(timestamp_ms) AS ts
        FROM derivatives
        WHERE symbol = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])


def insert_derivatives_snapshot(
    conn,
    symbol: str,
    ts_ms: int,
    open_interest: Optional[float],
    funding_rate: Optional[float],
    taker_buy_volume: Optional[float],
    taker_sell_volume: Optional[float],
    taker_buy_ratio: Optional[float],
) -> None:
    """
    Вставка строки в derivatives.
    Используем INSERT IGNORE, чтобы уникальный ключ (symbol, timestamp_ms)
    не ронял скрипт, если по какой-то причине уже есть запись за этот ts.
    """
    sql = """
        INSERT IGNORE INTO derivatives (
            symbol,
            timestamp_ms,
            open_interest,
            funding_rate,
            taker_buy_volume,
            taker_sell_volume,
            taker_buy_ratio
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                symbol,
                ts_ms,
                open_interest,
                funding_rate,
                taker_buy_volume,
                taker_sell_volume,
                taker_buy_ratio,
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
        # Привязываем к минутной сетке
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        minute_ms = 60_000
        ts_ms = (now_ms // minute_ms) * minute_ms

        last_ts = get_latest_timestamp_ms(conn, SYMBOL)
        if last_ts is not None and ts_ms <= last_ts:
            logger.info(
                "derivatives[%s]: already up to date (ts_ms=%s, last_ts=%s)",
                SYMBOL,
                ts_ms,
                last_ts,
            )
            return

        oi = None
        funding = None
        buy_vol = None
        sell_vol = None
        ratio = None

        # open interest
        try:
            oi = fetch_open_interest(SYMBOL)
        except Exception as e:
            logger.error("derivatives[%s]: error fetching open interest: %s", SYMBOL, e, exc_info=True)

        # funding rate
        try:
            funding = fetch_funding_rate(SYMBOL)
        except Exception as e:
            logger.error("derivatives[%s]: error fetching funding: %s", SYMBOL, e, exc_info=True)

        # taker stats (не критично, если упадёт)
        buy_vol, sell_vol, ratio = fetch_taker_stats(SYMBOL)

        insert_derivatives_snapshot(
            conn,
            SYMBOL,
            ts_ms,
            oi,
            funding,
            buy_vol,
            sell_vol,
            ratio,
        )

        logger.info(
            "derivatives[%s]: inserted snapshot ts=%s (oi=%s, funding=%s, buy_vol=%s, sell_vol=%s, ratio=%s)",
            SYMBOL,
            ts_ms,
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
