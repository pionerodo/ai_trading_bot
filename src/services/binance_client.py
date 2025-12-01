import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.config_loader import load_config

logger = logging.getLogger("ai_trading_bot")


@dataclass
class BinanceConfig:
    enabled: bool
    testnet: bool
    api_key: str
    api_secret: str
    symbol: str
    base_asset: str
    quote_asset: str
    max_leverage: int
    max_position_usd: float
    max_daily_loss_pct: float


def load_binance_config() -> BinanceConfig:
    """
    Читает блок binance из config.yaml.
    Если чего-то нет — подставляет безопасные дефолты.
    """
    cfg = load_config()
    b = cfg.get("binance", {}) or {}

    return BinanceConfig(
        enabled=bool(b.get("enabled", False)),
        testnet=bool(b.get("testnet", True)),
        api_key=str(b.get("api_key", "")),
        api_secret=str(b.get("api_secret", "")),
        symbol=str(b.get("symbol", "BTCUSDT")),
        base_asset=str(b.get("base_asset", "BTC")),
        quote_asset=str(b.get("quote_asset", "USDT")),
        max_leverage=int(b.get("max_leverage", 3)),
        max_position_usd=float(b.get("max_position_usd", 500.0)),
        max_daily_loss_pct=float(b.get("max_daily_loss_pct", 5.0)),
    )


class BinanceClient:
    """
    Каркас клиента Binance.

    ВАЖНО: на текущем этапе НИКАКИХ реальных запросов к бирже.
    Всё, что делает этот класс сейчас — логирует свои вызовы
    и возвращает безопасные заглушки.
    """

    def __init__(self, config: Optional[BinanceConfig] = None) -> None:
        self.config = config or load_binance_config()

        # Жёсткая защита: если enabled = False, любые попытки "торговать"
        # должны просто логироваться и игнорироваться.
        if not self.config.enabled:
            logger.info(
                "BinanceClient initialized in DISABLED mode "
                f"(testnet={self.config.testnet})"
            )
        else:
            logger.warning(
                "BinanceClient initialized with enabled=True. "
                "Пока не подключаем реальные ордера!"
            )

    # ====== Публичные методы, которые позже будем реализовывать ======

    def get_account_status(self) -> Dict[str, Any]:
        """
        Вернуть состояние аккаунта.

        Сейчас: просто заглушка, чтобы можно было вызвать из health-check.
        """
        logger.info(
            "BinanceClient.get_account_status() called "
            f"(enabled={self.config.enabled}, testnet={self.config.testnet})"
        )

        # Будущий формат ответа; пока — фиксированная заглушка
        return {
            "connected": False,
            "testnet": self.config.testnet,
            "enabled": self.config.enabled,
            "balances": [],
            "positions": [],
        }

    def open_position(self, side: str, qty: float, price: float) -> Dict[str, Any]:
        """
        Открытие позиции.

        Сейчас: ничего не делает, только логирует параметры.
        """
        logger.info(
            "BinanceClient.open_position() stub called: "
            f"side={side}, qty={qty}, price={price}, enabled={self.config.enabled}"
        )

        return {
            "status": "ignored",
            "reason": "binance_disabled",
            "side": side,
            "qty": qty,
            "price": price,
        }

    def close_position(self, side: str, qty: float, price: float) -> Dict[str, Any]:
        """
        Закрытие позиции.

        Сейчас: только лог.
        """
        logger.info(
            "BinanceClient.close_position() stub called: "
            f"side={side}, qty={qty}, price={price}, enabled={self.config.enabled}"
        )

        return {
            "status": "ignored",
            "reason": "binance_disabled",
            "side": side,
            "qty": qty,
            "price": price,
        }

    def cancel_all_orders(self) -> Dict[str, Any]:
        """
        В будущем — отмена всех лимиток перед сменой режима.

        Сейчас: заглушка.
        """
        logger.info(
            "BinanceClient.cancel_all_orders() stub called "
            f"(enabled={self.config.enabled})"
        )
        return {"status": "ignored", "reason": "binance_disabled"}
