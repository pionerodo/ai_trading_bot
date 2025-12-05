#!/usr/bin/env python3
"""
candles_collector.py

Задача:
- регулярно подтягивать новые свечи с Binance Futures (BTCUSDT)
- писать их в таблицу `candles` (MariaDB)
- работать идемпотентно: каждый запуск дозаливает только недостающие свечи

Предполагается:
- таблица `candles` уже создана (см. ai_trading_bot_table_candles.sql)
- поле `id` = AUTO_INCREMENT (если нет — сделай ALTER)
- есть модуль db_utils.py с функцией get_db_connection(), которая возвращает pymysql / mysqlclient connection
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import urllib.request
import urllib.parse

# Попытка импортировать get_db_connection из db_utils
try:
    from .db_utils import get_db_connection  # запуск как модуль: python -m src.data_collector.candles_collector
except ImportError:
    from db_utils import get_db_connection  # запуск напрямую: python src/data_collector/candles_collector.py


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
LOG_FILE = "logs/candles_collector.log"


# === ЛОГИРОВАНИЕ ===

def setup_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Попробуем писать в файл
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        # Если не получилось (нет папки logs и т.п.) — пишем в stdout
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


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

    Возвращает список словарей:
    {
        "open_time": int,
        "open": str,
        "high": str,
        "low": str,
        "close": str,
        "volume": str,
        "close_time": int
    }
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
        # Документация Binance Futures Klines:
        # [0] Open time
        # [1] Open
        # [2] High
        # [3] Low
        # [4] Close
        # [5] Volume
        # [6] Close time
        # ...
        k = {
            "open_time": int(row[0]),
            "open": str(row[1]),
            "high": str(row[2]),
            "low": str(row[3]),
            "close": str(row[4]),
            "volume": str(row[5]),
            "close_time": int(row[6]),
        }
        klines.append(k)

    return klines


def get_latest_open_time(
    conn,
    symbol: str,
    timeframe: str,
) -> Optional[int]:
    """
    Возвращает MAX(open_time) для пары+таймфрейма в таблице `candles`.
    Если таблица пустая — возвращает None.
    """
    sql = """
        SELECT MAX(open_time) AS max_open_time
        FROM candles
        WHERE symbol = %s AND timeframe = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, timeframe))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])


def insert_candles(
    conn,
    symbol: str,
    timeframe: str,
    candles: List[Dict[str, Any]],
) -> int:
    """
    Вставляет пачку свечей в таблицу `candles`.

    ВАЖНО:
    - предполагаем, что поле `id` = AUTO_INCREMENT,
      поэтому его не указываем в INSERT.
    """
    if not candles:
        return 0

    sql = """
        INSERT INTO candles (
            symbol,
            timeframe,
            open_time,
            `open`,
            high,
            low,
            `close`,
            volume,
            close_time
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    inserted = 0
    with conn.cursor() as cur:
        for c in candles:
            params = (
                symbol,
                timeframe,
                int(c["open_time"]),
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                c["volume"],
                int(c["close_time"]),
            )
            cur.execute(sql, params)
            inserted += 1

    conn.commit()
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
        # Таблица пустая → берём историю за LOOKBACK_MINUTES_IF_EMPTY
        start_time_ms = now_ms - LOOKBACK_MINUTES_IF_EMPTY * 60_000
        logger.info(
            "candles[%s, %s]: table empty, starting from %s",
            symbol,
            timeframe,
            datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).isoformat(),
        )
    else:
        # Начинаем со следующей свечи
        start_time_ms = last_open_time + step_ms
        logger.info(
            "candles[%s, %s]: last open_time = %s, starting from next candle",
            symbol,
            timeframe,
            datetime.fromtimestamp(last_open_time / 1000, tz=timezone.utc).isoformat(),
        )

    if start_time_ms >= now_ms:
        logger.info(
            "candles[%s, %s]: up to date (start_time_ms >= now_ms), nothing to do",
            symbol,
            timeframe,
        )
        return

    total_inserted = 0
    current_start = start_time_ms

    while current_start < now_ms:
        # Чтобы не запрашивать слишком далеко вперёд
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
            logger.error(
                "candles[%s, %s]: error fetching klines from Binance: %s",
                symbol,
                timeframe,
                e,
                exc_info=True,
            )
            # Не падаем полностью, просто выходим из цикла по этому ТФ
            break

        if not klines:
            logger.info(
                "candles[%s, %s]: no klines returned (start=%s, end=%s), stopping",
                symbol,
                timeframe,
                current_start,
                batch_end,
            )
            break

        # Защита от редких дублей: если вдруг Binance вернул свечу с open_time <= last_known
        klines = [k for k in klines if k["open_time"] >= start_time_ms]
        if not klines:
            break

        try:
            inserted = insert_candles(conn, symbol, timeframe, klines)
            total_inserted += inserted
            logger.info(
                "candles[%s, %s]: inserted %d candles (batch), total_inserted=%d",
                symbol,
                timeframe,
                inserted,
                total_inserted,
            )
        except Exception as e:
            logger.error(
                "candles[%s, %s]: error inserting candles into DB: %s",
                symbol,
                timeframe,
                e,
                exc_info=True,
            )
            # Если тут ошибка — не продолжаем, т.к. можем получить дубль/несогласованность
            break

        # Следующая партия начинается с конца последней свечи + 1 шаг
        last_batch_open = klines[-1]["open_time"]
        current_start = last_batch_open + step_ms

        # Маленькая пауза, чтобы не спамить Binance
        time.sleep(0.1)

    logger.info(
        "candles[%s, %s]: done, total inserted = %d",
        symbol,
        timeframe,
        total_inserted,
    )


def main() -> None:
    setup_logging()
    logger.info("candles_collector: started")

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("candles_collector: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        for tf in TIMEFRAMES:
            collect_for_timeframe(conn, SYMBOL, tf)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("candles_collector: finished")


if __name__ == "__main__":
    main()
