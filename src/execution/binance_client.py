import logging
import time
from typing import Optional

from binance.client import Client

from src.config import BinanceConfig, get_binance_config
from src.execution.execution_logger import log_execution_event, log_risk_event

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self, config: Optional[BinanceConfig] = None, db_session_factory=None):
        self.config = config or get_binance_config()
        self.db_session_factory = db_session_factory

        self.client = Client(self.config.api_key, self.config.api_secret, testnet=self.config.testnet)
        if self.config.testnet:
            # Explicitly pin testnet futures endpoint
            self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"

    def _with_retries(self, action: str, func, *args, **kwargs):
        attempts = 0
        backoff = 1
        last_exc: Optional[Exception] = None

        while attempts < 3:
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                attempts += 1
                last_exc = exc
                logger.warning("Binance action %s failed attempt %s: %s", action, attempts, exc)
                time.sleep(backoff)
                backoff *= 2

        if self.db_session_factory:
            log_risk_event(
                self.db_session_factory,
                event_type="BINANCE_API_FAILURE",
                symbol=kwargs.get("symbol", self.config.base_asset),
                details=f"Action {action} failed after {attempts} attempts",
                extra={"error": str(last_exc)},
            )
        raise last_exc or RuntimeError("Binance action failed")

    def get_price(self, symbol: str):
        resp = self._with_retries("get_price", self.client.ticker_price, symbol=symbol)
        price = resp.get("price") if isinstance(resp, dict) else None
        return float(price) if price is not None else None

    def get_position(self, symbol: str):
        data = self._with_retries(
            "get_position",
            self.client.futures_position_information,
            symbol=symbol,
        )
        return data[0] if data else None

    def get_open_orders(self, symbol: str):
        return self._with_retries("get_open_orders", self.client.futures_get_open_orders, symbol=symbol)

    def send_limit_order(self, symbol: str, side: str, qty, price, clientOrderId: str):
        return self._with_retries(
            "send_limit_order",
            self.client.futures_create_order,
            symbol=symbol,
            side=side.upper(),
            type="LIMIT",
            quantity=qty,
            price=price,
            timeInForce="GTC",
            newClientOrderId=clientOrderId,
        )

    def send_market_order(self, symbol: str, side: str, qty, clientOrderId: str):
        return self._with_retries(
            "send_market_order",
            self.client.futures_create_order,
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=qty,
            newClientOrderId=clientOrderId,
        )

    def cancel_order(self, symbol: str, clientOrderId: str):
        return self._with_retries(
            "cancel_order",
            self.client.futures_cancel_order,
            symbol=symbol,
            origClientOrderId=clientOrderId,
        )

    def cancel_all_orders(self, symbol: str):
        return self._with_retries(
            "cancel_all_orders",
            self.client.futures_cancel_all_open_orders,
            symbol=symbol,
        )
