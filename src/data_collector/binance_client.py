from typing import List, Any

import httpx
import logging


logger = logging.getLogger("ai_trading_bot")

BASE_URL = "https://api.binance.com"


class BinanceError(Exception):
    pass


def get_klines(symbol: str, interval: str, limit: int = 500) -> List[Any]:
    """
    Получает свежие свечи с Binance (spot).
    interval: '1m', '5m', '15m', '1h' и т.д.
    """
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.exception("Error fetching klines from Binance: %s", e)
        raise BinanceError(str(e)) from e

    return resp.json()
