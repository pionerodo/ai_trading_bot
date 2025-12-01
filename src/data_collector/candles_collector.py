from typing import Tuple

from sqlalchemy.orm import Session

from src.db.models import Candle
from src.data_collector.binance_client import get_klines
import logging


logger = logging.getLogger("ai_trading_bot")


def sync_candles_for_timeframe(
    db: Session,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> Tuple[int, int]:
    """
    Синхронизирует последние свечи Binance в таблицу candles.
    Возвращает (новых, всего_в_таблице_для_таймфрейма).
    """

    # 1. Находим последнюю свечу в БД
    last = (
        db.query(Candle)
        .filter(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(Candle.open_time.desc())
        .first()
    )
    last_open_time = last.open_time if last else 0

    # 2. Берём свежие свечи с Binance
    klines = get_klines(symbol=symbol, interval=timeframe, limit=limit)

    inserted = 0
    for k in klines:
        open_time_ms = int(k[0])
        close_time_ms = int(k[6])

        if open_time_ms <= last_open_time:
            # уже есть в БД
            continue

        candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time_ms,
            open=k[1],
            high=k[2],
            low=k[3],
            close=k[4],
            volume=k[5],
            close_time=close_time_ms,
        )
        db.add(candle)
        inserted += 1

    if inserted > 0:
        db.commit()

    total = (
        db.query(Candle)
        .filter(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .count()
    )

    logger.info(
        "Candles sync: symbol=%s tf=%s inserted=%s total=%s",
        symbol,
        timeframe,
        inserted,
        total,
    )

    return inserted, total
