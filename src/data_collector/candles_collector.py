#!/usr/bin/env python3
"""
Candles Collector

- регулярно подтягивает новые свечи с Binance Futures (BTCUSDT)
- пишет их в таблицу `candles` (MariaDB)
- работает идемпотентно: каждый запуск дозаливает только недостающие свечи

Схема БД (DATABASE_SCHEMA.md):
- open_time / close_time: DATETIME (UTC, naive)
- open_price/high_price/low_price/close_price, volume, quote_volume, trades_count
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import urllib.parse
import urllib.request

# --- Ensure project root on sys.path for cron execution ---
CURRENT_FILE = os.path.abspath(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_FILE)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.metrics import get_metrics_snapshot, increment_metric
from src.core.structured_logging import log_error, log_info, log_warning
from src.data_collector.db_utils import get_db_connection

# === НАСТРОЙКИ COLLECTOR'А ===

SYMBOL = "BTCUSDT"

# Какие таймфреймы собираем
TIMEFRAMES = ["1m", "5m", "15m", "1h"]

# Сколько истории подтягивать, если таблица пустая (в минутах)
LOOKBACK_MINUTES_IF_EMPTY = 24 * 60  # 1 день

# Максимум свечей за один запрос к Binance (ограничение API)
BINANCE_MAX_LIMIT = 1000

# Базовый URL Binance Futures
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

# Путь к логам (если папка logs не существует — будет лог в stdout)
LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "candles_collector.log")


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


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def timeframe_to_ms(tf: str) -> int:
    """Перевод таймфрейма Binance в миллисекунды."""
    mapping = {
        "1m": 60_000,
        "3m": 3 * 60_000,
        "5m": 5 * 60_000,
        "15m": 15 * 60_000,
        "30m": 30 * 60_000,
        "1h": 60 * 60_000,
        "2h": 2 * 60 * 60_000,
        "4h": 4 * 60 * 60_000,
        "1d": 24 * 60 * 60_000,
    }
    if tf not in mapping:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return mapping[tf]


def http_get(url: str, params: Dict[str, Any]) -> Any:
    """Простой GET через стандартную библиотеку (без дополнительных зависимостей)."""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data)


def fetch_klines(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: Optional[int] = None,
    limit: int = BINANCE_MAX_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Получает список свечей с Binance Futures.

    Возвращает список словарей с ключами, совместимыми со схемой `candles`.
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time_ms,
        "limit": limit,
    }
    if end_time_ms is not None:
        params["endTime"] = end_time_ms

    url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/klines"
    raw = http_get(url, params)

    klines: List[Dict[str, Any]] = []
    for row in raw:
        k = {
            "open_time": int(row[0]),
            "open": str(row[1]),
            "high": str(row[2]),
            "low": str(row[3]),
            "close": str(row[4]),
            "volume": str(row[5]),
            "close_time": int(row[6]),
            "quote_volume": str(row[7]) if len(row) > 7 else None,
            "trades_count": int(row[8]) if len(row) > 8 else None,
        }
        klines.append(k)

    return klines


def get_latest_open_time(conn, symbol: str, timeframe: str) -> Optional[int]:
    """
    Возвращает MAX(open_time) для пары+таймфрейма в таблице `candles` (DATETIME UTC, naive).
    Если таблица пустая — возвращает None. Возвращаемое значение — millis.
    """
    sql = """
        SELECT MAX(open_time) AS max_open_time
        FROM candles
        WHERE symbol = %s AND timeframe = %s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, timeframe))
            row = cur.fetchone()
    except Exception as exc:
        increment_metric(
            "candles_select_failures",
            labels={"symbol": symbol, "timeframe": timeframe},
        )
        log_error(
            logger,
            "candles_latest_open_time_failed",
            symbol=symbol,
            timeframe=timeframe,
            error=str(exc),
        )
        return None

    if not row or row[0] is None:
        return None
    try:
        return int(row[0].timestamp() * 1000)
    except Exception as exc:
        log_warning(
            logger,
            "candles_latest_open_time_invalid",
            symbol=symbol,
            timeframe=timeframe,
            raw_value=str(row[0]),
            error=str(exc),
        )
        return None


def insert_candles(
    conn,
    symbol: str,
    timeframe: str,
    candles: List[Dict[str, Any]],
) -> int:
    """Вставляет пачку свечей в таблицу `candles` по актуальной схеме."""
    if not candles:
        return 0

    sql = """
        INSERT INTO candles (
            symbol,
            timeframe,
            open_time,
            close_time,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            quote_volume,
            trades_count
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            close_time=VALUES(close_time),
            open_price=VALUES(open_price),
            high_price=VALUES(high_price),
            low_price=VALUES(low_price),
            close_price=VALUES(close_price),
            volume=VALUES(volume),
            quote_volume=VALUES(quote_volume),
            trades_count=VALUES(trades_count)
    """

    inserted = 0
    try:
        with conn.cursor() as cur:
            for c in candles:
                open_dt = datetime.utcfromtimestamp(int(c["open_time"]) / 1000)
                close_dt = datetime.utcfromtimestamp(int(c["close_time"]) / 1000)
                params = (
                    symbol,
                    timeframe,
                    open_dt,
                    close_dt,
                    c["open"],
                    c["high"],
                    c["low"],
                    c["close"],
                    c["volume"],
                    c.get("quote_volume"),
                    c.get("trades_count"),
                )
                cur.execute(sql, params)
                inserted += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        increment_metric(
            "candles_insert_failures",
            labels={"symbol": symbol, "timeframe": timeframe},
        )
        log_error(
            logger,
            "candles_insert_failed",
            symbol=symbol,
            timeframe=timeframe,
            error=str(exc),
        )
        raise

    return inserted


# === ОСНОВНАЯ ЛОГИКА ===

def collect_for_timeframe(conn, symbol: str, timeframe: str) -> None:
    """
    Обновляет свечи для одного таймфрейма:
    - определяем, откуда начинать (MAX(open_time) + 1 свеча или lookback)
    - допрашиваем Binance батчами до текущего времени
    - пишем в БД
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    step_ms = timeframe_to_ms(timeframe)

    last_open_time = get_latest_open_time(conn, symbol, timeframe)

    if last_open_time is None:
        start_time_ms = now_ms - LOOKBACK_MINUTES_IF_EMPTY * 60_000
        log_info(
            logger,
            "candles_bootstrap",
            symbol=symbol,
            timeframe=timeframe,
            start_at=datetime.fromtimestamp(
                start_time_ms / 1000, tz=timezone.utc
            ).isoformat(),
        )
    else:
        start_time_ms = last_open_time + step_ms
        log_info(
            logger,
            "candles_resume",
            symbol=symbol,
            timeframe=timeframe,
            last_open_time=datetime.fromtimestamp(
                last_open_time / 1000, tz=timezone.utc
            ).isoformat(),
        )

    if start_time_ms >= now_ms:
        log_info(
            logger,
            "candles_up_to_date",
            symbol=symbol,
            timeframe=timeframe,
        )
        return

    total_inserted = 0
    current_start = start_time_ms

    while current_start < now_ms:
        batch_end = min(now_ms, current_start + step_ms * BINANCE_MAX_LIMIT)

        try:
            klines = fetch_klines(
                symbol=symbol,
                interval=timeframe,
                start_time_ms=current_start,
                end_time_ms=batch_end,
                limit=BINANCE_MAX_LIMIT,
            )
        except Exception as e:
            increment_metric(
                "candles_fetch_failures",
                labels={"symbol": symbol, "timeframe": timeframe},
            )
            log_error(
                logger,
                "candles_fetch_failed",
                symbol=symbol,
                timeframe=timeframe,
                start_ms=current_start,
                end_ms=batch_end,
                error=str(e),
            )
            break

        if not klines:
            log_warning(
                logger,
                "candles_empty_batch",
                symbol=symbol,
                timeframe=timeframe,
                start_ms=current_start,
                end_ms=batch_end,
            )
            break

        klines = [k for k in klines if k["open_time"] >= start_time_ms]
        if not klines:
            break

        try:
            inserted = insert_candles(conn, symbol, timeframe, klines)
            total_inserted += inserted
            log_info(
                logger,
                "candles_batch_inserted",
                symbol=symbol,
                timeframe=timeframe,
                inserted=inserted,
                total_inserted=total_inserted,
            )
        except Exception:
            # Detailed logging and metrics are handled inside insert_candles().
            break

        last_batch_open = klines[-1]["open_time"]
        current_start = last_batch_open + step_ms

        time.sleep(0.1)

    log_info(
        logger,
        "candles_collect_complete",
        symbol=symbol,
        timeframe=timeframe,
        total_inserted=total_inserted,
    )


def main() -> None:
    setup_logging()
    log_info(logger, "candles_collector_started", symbol=SYMBOL, timeframes=TIMEFRAMES)

    try:
        conn = get_db_connection()
    except Exception as e:
        increment_metric("candles_db_connection_failures", labels={"symbol": SYMBOL})
        log_error(
            logger,
            "candles_db_connection_failed",
            symbol=SYMBOL,
            timeframes=TIMEFRAMES,
            error=str(e),
        )
        sys.exit(1)

    try:
        for tf in TIMEFRAMES:
            collect_for_timeframe(conn, SYMBOL, tf)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    log_info(
        logger,
        "candles_collector_finished",
        symbol=SYMBOL,
        timeframes=TIMEFRAMES,
        metrics=get_metrics_snapshot(),
    )


if __name__ == "__main__":
    main()
