import logging
from typing import Optional

from src.config import get_binance_config
from src.db.models import Order, Position
from src.execution.binance_client import BinanceClient
from src.execution.execution_logger import log_risk_event

logger = logging.getLogger(__name__)


def reconcile_exchange_state(db_session_factory, symbol: str, binance_client: Optional[BinanceClient] = None) -> None:
    """
    Load open orders and position from Binance and compare to local state.
    Records RiskEvents on divergence for manual follow-up.
    """

    client = binance_client
    if client is None:
        client = BinanceClient(config=get_binance_config(), db_session_factory=db_session_factory)

    try:
        remote_orders = client.get_open_orders(symbol)
    except Exception as exc:  # noqa: BLE001
        log_risk_event(
            db_session_factory,
            event_type="RECONCILE_FETCH_ORDERS_FAILED",
            symbol=symbol,
            details=str(exc),
        )
        remote_orders = None

    try:
        remote_position = client.get_position(symbol)
    except Exception as exc:  # noqa: BLE001
        log_risk_event(
            db_session_factory,
            event_type="RECONCILE_FETCH_POSITION_FAILED",
            symbol=symbol,
            details=str(exc),
        )
        remote_position = None

    with db_session_factory() as session:
        local_orders = session.query(Order).filter(Order.symbol == symbol, Order.status.in_(["new", "working"])).all()
        local_position = session.query(Position).filter(Position.symbol == symbol, Position.status == "open").first()

    _compare_orders(db_session_factory, symbol, local_orders, remote_orders or [])
    _compare_position(db_session_factory, symbol, local_position, remote_position)


def _compare_orders(db_session_factory, symbol: str, local_orders, remote_orders) -> None:
    remote_index = {o.get("clientOrderId"): o for o in remote_orders}
    for order in local_orders:
        remote = remote_index.get(order.client_order_id)
        if remote is None:
            log_risk_event(
                db_session_factory,
                event_type="RECONCILE_ORDER_MISSING_ON_EXCHANGE",
                symbol=symbol,
                details=f"Local order {order.client_order_id} not on exchange",
                extra={"order_id": order.id, "role": order.role},
            )
        elif str(remote.get("status", "")) != str(order.status):
            log_risk_event(
                db_session_factory,
                event_type="RECONCILE_ORDER_STATUS_MISMATCH",
                symbol=symbol,
                details=f"Order {order.client_order_id} status mismatch local={order.status} remote={remote.get('status')}",
                extra={"order_id": order.id, "role": order.role},
            )


def _compare_position(db_session_factory, symbol: str, local_position: Optional[Position], remote_position) -> None:
    remote_qty = float(remote_position.get("positionAmt", 0)) if remote_position else 0.0
    if local_position is None and abs(remote_qty) > 0:
        log_risk_event(
            db_session_factory,
            event_type="RECONCILE_PHANTOM_EXCHANGE_POSITION",
            symbol=symbol,
            details=f"Exchange shows qty {remote_qty} but no local position",
        )
        return
    if local_position and abs(remote_qty) == 0:
        log_risk_event(
            db_session_factory,
            event_type="RECONCILE_MISSING_EXCHANGE_POSITION",
            symbol=symbol,
            details=f"Local position {local_position.id} open but exchange qty=0",
        )
        return
    if local_position:
        side = 1 if local_position.side == "long" else -1
        local_qty = float(local_position.size) * side
        if abs(local_qty - remote_qty) > 1e-6:
            log_risk_event(
                db_session_factory,
                event_type="RECONCILE_POSITION_QTY_MISMATCH",
                symbol=symbol,
                details=f"Local qty {local_qty} vs exchange {remote_qty}",
                extra={"position_id": local_position.id},
            )
