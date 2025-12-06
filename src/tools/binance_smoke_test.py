"""Binance Testnet smoke test utility.

Run a minimal set of calls against the Binance testnet adapter to validate
credentials, connectivity, and basic order lifecycle. The script exits after
one run and is safe to invoke manually.
"""

import logging
import sys
import time
from decimal import Decimal
from typing import Optional

from src.config import get_binance_config
from src.db.models import Order
from src.db.session import SessionLocal
from src.execution.binance_client import BinanceClient
from src.execution.execution_logger import log_execution_event, log_risk_event


logger = logging.getLogger(__name__)

# Optional notifier placeholder
def notify_critical(message: str, context: Optional[dict] = None) -> None:
    logger.warning("NOTIFY: %s | %s", message, context or {})


def _get_dry_run_flag() -> bool:
    raw = sys.argv[1] if len(sys.argv) > 1 else None
    if raw is None:
        import os

        raw = os.getenv("SMOKE_DRY_RUN_ORDER", "1")
    return str(raw).strip().lower() in {"1", "true", "yes", "y"}


def main(symbol: str = "BTCUSDT") -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    dry_run = _get_dry_run_flag()

    try:
        cfg = get_binance_config()
        client = BinanceClient(config=cfg, db_session_factory=SessionLocal)
    except Exception as exc:  # noqa: BLE001
        log_risk_event(SessionLocal, event_type="BINANCE_SMOKE_INIT_FAIL", symbol=symbol, details=str(exc))
        notify_critical("Binance smoke init failed", {"error": str(exc)})
        sys.exit(1)

    try:
        price = client.get_price(symbol)
        position = client.get_position(symbol)
        orders = client.get_open_orders(symbol)

        log_execution_event(
            SessionLocal,
            module="binance_smoke_test",
            level="INFO",
            message="Smoke test fetched data",
            context={"price": price, "position": position, "orders_count": len(orders or [])},
        )

        if dry_run:
            logger.info("Dry run enabled; skipping order placement")
            return

        qty = Decimal("0.001")
        target_price = Decimal(str(price)) if price else Decimal("0")
        if target_price > 0:
            target_price *= Decimal("0.5")  # unlikely to fill quickly on testnet
        client_order_id = f"SMOKE_{int(time.time() * 1000)}"

        order_resp = client.send_limit_order(symbol, side="BUY", qty=float(qty), price=float(target_price), clientOrderId=client_order_id)
        log_execution_event(
            SessionLocal,
            module="binance_smoke_test",
            level="INFO",
            message="Placed smoke-test limit order",
            context={"client_order_id": client_order_id, "price": str(target_price), "qty": str(qty)},
        )

        with SessionLocal() as session:
            db_order = Order(
                client_order_id=client_order_id,
                exchange_order_id=order_resp.get("orderId"),
                symbol=symbol,
                role="manual_exit",
                side="buy",
                order_type="limit",
                status=str(order_resp.get("status", "new")),
                price=target_price,
                orig_qty=qty,
                executed_qty=Decimal(str(order_resp.get("executedQty", 0) or 0)),
                json_data=order_resp,
            )
            session.add(db_order)
            session.commit()

        cancel_resp = client.cancel_order(symbol, clientOrderId=client_order_id)
        log_execution_event(
            SessionLocal,
            module="binance_smoke_test",
            level="INFO",
            message="Canceled smoke-test limit order",
            context={"client_order_id": client_order_id, "cancel": cancel_resp},
        )
    except Exception as exc:  # noqa: BLE001
        log_risk_event(SessionLocal, event_type="BINANCE_SMOKE_FAILURE", symbol=symbol, details=str(exc))
        notify_critical("Binance smoke test failed", {"error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
