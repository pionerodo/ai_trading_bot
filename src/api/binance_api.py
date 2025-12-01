import logging
from fastapi import APIRouter

from src.services.binance_client import BinanceClient, load_binance_config

logger = logging.getLogger("ai_trading_bot")

router = APIRouter()


@router.get("/health")
def binance_health():
    """
    Безопасный health-check Binance.

    Все методы BinanceClient в этом этапе — заглушки, поэтому:
    - НЕ происходит никаких реальных запросов
    - статус всегда "connected": False
    """

    config = load_binance_config()
    client = BinanceClient(config)

    status = client.get_account_status()

    return {
        "binance_enabled": config.enabled,
        "testnet": config.testnet,
        "status": status,
    }
