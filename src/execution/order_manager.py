import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from src.config import BinanceConfig, get_binance_config
from src.db.models import Order, Position
from src.execution.binance_client import BinanceClient
from src.execution.execution_logger import log_execution_event, log_risk_event

logger = logging.getLogger(__name__)


_ACTIVE_STATUSES = ("new", "working")
_FILLED_STATUSES = ("filled",)


class OrderManager:
    def __init__(
        self,
        db_session_factory,
        symbol: str = "BTCUSDT",
        binance_client: Optional[BinanceClient] = None,
        binance_config: Optional[BinanceConfig] = None,
    ):
        self.db_session_factory = db_session_factory
        self.symbol = symbol
        config = binance_config or get_binance_config()
        self.binance = binance_client or BinanceClient(config=config, db_session_factory=db_session_factory)

    def _get_session(self) -> Session:
        return self.db_session_factory()

    def _generate_client_order_id(self, position_id: int, role: str, decision_id: Optional[int]) -> str:
        decision_part = f"{decision_id}" if decision_id is not None else "na"
        return f"{decision_part}_{position_id}_{role}"

    def _find_active_order(self, session: Session, position_id: int, role: str) -> Optional[Order]:
        return (
            session.query(Order)
            .filter(
                Order.position_id == position_id,
                Order.role == role,
                Order.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(Order.updated_at_utc.desc())
            .first()
        )

    def _sync_core_fields(
        self,
        order: Order,
        *,
        side: str,
        role: str,
        price: Optional[Decimal],
        stop_price: Optional[Decimal],
        orig_qty: Decimal,
        order_type: str,
        decision_id: Optional[int],
        position_id: int,
    ) -> None:
        order.side = side
        order.role = role
        order.price = price
        order.stop_price = stop_price
        order.orig_qty = orig_qty
        order.order_type = order_type
        order.decision_id = decision_id
        order.position_id = position_id
        order.symbol = self.symbol

    def build_entry_order(self, position: Position, decision: dict) -> Order:
        price = decision.get("entry_price")
        if price is None:
            entry_min = decision.get("entry_min_price")
            entry_max = decision.get("entry_max_price")
            if entry_min is not None and entry_max is not None:
                price = (Decimal(str(entry_min)) + Decimal(str(entry_max))) / Decimal("2")
        price_dec = Decimal(str(price)) if price is not None else None

        role = "entry"
        side = "buy" if position.side == "long" else "sell"
        decision_id = decision.get("decision_id") or decision.get("id")
        order_type = decision.get("order_type") or "limit"

        with self._get_session() as session:
            existing = self._find_active_order(session, position.id, role)
            qty = Decimal(str(position.size))
            if existing and self._matches(existing, side, price_dec, None, qty):
                return existing

            order = existing or Order(
                client_order_id=self._generate_client_order_id(position.id, role, decision_id),
                role=role,
                side=side,
                order_type=order_type,
                status="new",
                decision_id=decision_id,
                position_id=position.id,
                symbol=self.symbol,
            )
            self._sync_core_fields(
                order,
                side=side,
                role=role,
                price=price_dec,
                stop_price=None,
                orig_qty=qty,
                order_type=order_type,
                decision_id=decision_id,
                position_id=position.id,
            )
            return self.place_or_update(order, session=session)

    def build_sl_order(self, position: Position) -> Order:
        if position.sl_price is None:
            raise ValueError("Position SL price is required to build SL order")

        role = "sl"
        side = "sell" if position.side == "long" else "buy"
        stop_price = Decimal(str(position.sl_price))

        with self._get_session() as session:
            existing = self._find_active_order(session, position.id, role)
            qty = Decimal(str(position.size))
            if existing and self._matches(existing, side, None, stop_price, qty):
                return existing

            order = existing or Order(
                client_order_id=self._generate_client_order_id(position.id, role, position.decision_id),
                role=role,
                side=side,
                order_type="stop",
                status="new",
                decision_id=position.decision_id,
                position_id=position.id,
                symbol=self.symbol,
            )
            self._sync_core_fields(
                order,
                side=side,
                role=role,
                price=None,
                stop_price=stop_price,
                orig_qty=qty,
                order_type="stop",
                decision_id=position.decision_id,
                position_id=position.id,
            )
            return self.place_or_update(order, session=session)

    def build_tp_orders(self, position: Position) -> Tuple[Optional[Order], Optional[Order]]:
        tp1_order = None
        tp2_order = None
        size = Decimal(str(position.size))

        tp1_qty = size / Decimal("2")
        tp2_qty = size - tp1_qty

        with self._get_session() as session:
            if position.tp1_price:
                tp1_order = self._build_or_update_tp(
                    session=session,
                    position=position,
                    role="tp1",
                    price=Decimal(str(position.tp1_price)),
                    qty=tp1_qty if position.tp2_price else size,
                )
            if position.tp2_price:
                tp2_order = self._build_or_update_tp(
                    session=session,
                    position=position,
                    role="tp2",
                    price=Decimal(str(position.tp2_price)),
                    qty=tp2_qty,
                )
        return tp1_order, tp2_order

    def _build_or_update_tp(
        self,
        session: Session,
        position: Position,
        role: str,
        price: Decimal,
        qty: Decimal,
    ) -> Order:
        side = "sell" if position.side == "long" else "buy"
        existing = self._find_active_order(session, position.id, role)
        if existing and self._matches(existing, side, price, None, qty):
            return existing

        order = existing or Order(
            client_order_id=self._generate_client_order_id(position.id, role, position.decision_id),
            role=role,
            side=side,
            order_type="limit",
            status="new",
            decision_id=position.decision_id,
            position_id=position.id,
            symbol=self.symbol,
        )
        self._sync_core_fields(
            order,
            side=side,
            role=role,
            price=price,
            stop_price=None,
            orig_qty=qty,
            order_type="limit",
            decision_id=position.decision_id,
            position_id=position.id,
        )
        return self.place_or_update(order, session=session)

    def place_entry_order(self, position: Position, decision: dict) -> Order:
        order = self.build_entry_order(position, decision)
        client_id = order.client_order_id
        price = order.price
        qty = order.orig_qty

        if order.order_type == "limit" and price is None:
            raise ValueError("Limit entry requires price")

        resp = (
            self.binance.send_limit_order(
                self.symbol,
                side=order.side,
                qty=float(qty),
                price=float(price) if price is not None else None,
                clientOrderId=client_id,
            )
            if order.order_type == "limit"
            else self.binance.send_market_order(
                self.symbol, side=order.side, qty=float(qty), clientOrderId=client_id
            )
        )
        self._update_order_after_exchange(order, resp)
        log_execution_event(
            self.db_session_factory,
            module="order_manager",
            level="INFO",
            message="ENTRY_ORDER_PLACED",
            context={"position_id": position.id, "decision_id": position.decision_id, "order_id": order.id},
        )
        return order

    def place_sl_order(self, position: Position) -> Order:
        order = self.build_sl_order(position)
        resp = self.binance._with_retries(  # noqa: SLF001
            "send_sl_order",
            self.binance.client.futures_create_order,
            symbol=self.symbol,
            side=order.side.upper(),
            type="STOP_MARKET",
            stopPrice=float(order.stop_price),
            closePosition=True,
            quantity=float(order.orig_qty),
            newClientOrderId=order.client_order_id,
        )
        self._update_order_after_exchange(order, resp)
        log_execution_event(
            self.db_session_factory,
            module="order_manager",
            level="INFO",
            message="SL_ORDER_PLACED",
            context={"position_id": position.id, "order_id": order.id, "client_order_id": order.client_order_id},
        )
        return order

    def place_tp1_order(self, position: Position, qty: Decimal) -> Order:
        if position.tp1_price is None:
            raise ValueError("TP1 price missing")
        order = self._build_tp_single(position, role="tp1", price=Decimal(str(position.tp1_price)), qty=qty)
        resp = self.binance._with_retries(  # noqa: SLF001
            "send_tp1_order",
            self.binance.client.futures_create_order,
            symbol=self.symbol,
            side=order.side.upper(),
            type="LIMIT",
            timeInForce="GTC",
            quantity=float(order.orig_qty),
            price=float(order.price),
            reduceOnly=True,
            newClientOrderId=order.client_order_id,
        )
        self._update_order_after_exchange(order, resp)
        log_execution_event(
            self.db_session_factory,
            module="order_manager",
            level="INFO",
            message="TP1_ORDER_PLACED",
            context={"position_id": position.id, "order_id": order.id},
        )
        return order

    def place_tp2_order(self, position: Position, qty: Decimal) -> Order:
        if position.tp2_price is None:
            raise ValueError("TP2 price missing")
        order = self._build_tp_single(position, role="tp2", price=Decimal(str(position.tp2_price)), qty=qty)
        resp = self.binance._with_retries(  # noqa: SLF001
            "send_tp2_order",
            self.binance.client.futures_create_order,
            symbol=self.symbol,
            side=order.side.upper(),
            type="LIMIT",
            timeInForce="GTC",
            quantity=float(order.orig_qty),
            price=float(order.price),
            reduceOnly=True,
            newClientOrderId=order.client_order_id,
        )
        self._update_order_after_exchange(order, resp)
        log_execution_event(
            self.db_session_factory,
            module="order_manager",
            level="INFO",
            message="TP2_ORDER_PLACED",
            context={"position_id": position.id, "order_id": order.id},
        )
        return order

    def cancel_stale_orders(self, position_id: int) -> int:
        canceled = self.cancel_stale_for_position(position_id)
        try:
            self.binance.cancel_all_orders(self.symbol)
        except Exception as exc:  # noqa: BLE001
            log_risk_event(
                self.db_session_factory,
                event_type="BINANCE_CANCEL_FAILED",
                symbol=self.symbol,
                details=str(exc),
                extra={"position_id": position_id},
            )
        return canceled

    def update_orders_status(self, position_id: int) -> None:
        """Pull open orders from Binance and sync statuses locally."""
        try:
            remote_orders = self.binance.get_open_orders(self.symbol)
        except Exception as exc:  # noqa: BLE001
            log_risk_event(
                self.db_session_factory,
                event_type="BINANCE_FETCH_ORDERS_FAILED",
                symbol=self.symbol,
                details=str(exc),
                extra={"position_id": position_id},
            )
            return

        remote_index = {o.get("clientOrderId"): o for o in remote_orders or []}

        with self._get_session() as session:
            orders = session.query(Order).filter(Order.position_id == position_id).all()
            now = datetime.utcnow()
            for order in orders:
                if order.client_order_id in remote_index:
                    order.status = remote_index[order.client_order_id].get("status", order.status)
                elif order.status in _ACTIVE_STATUSES:
                    order.status = "canceled"
                order.updated_at_utc = now
            session.commit()

    def place_or_update(self, order: Order, session: Optional[Session] = None) -> Order:
        manage_session = session is None
        session = session or self._get_session()
        now = datetime.utcnow()

        if not order.client_order_id:
            order.client_order_id = self._generate_client_order_id(
                order.position_id or 0, order.role, order.decision_id
            )

        if order.id is None:
            order.created_at_utc = now
        order.updated_at_utc = now

        if order.status in _ACTIVE_STATUSES:
            order.status = "working"
        elif not order.status:
            order.status = "working"

        session.add(order)
        session.commit()
        session.refresh(order)

        if manage_session:
            session.close()

        return order

    def cancel_stale_for_position(self, position_id: int) -> int:
        with self._get_session() as session:
            q = session.query(Order).filter(
                Order.position_id == position_id,
                ~Order.status.in_(_FILLED_STATUSES),
            )
            count = 0
            now = datetime.utcnow()
            for order in q:
                order.status = "canceled"
                order.updated_at_utc = now
                count += 1
            session.commit()
            return count

    def _build_tp_single(self, position: Position, role: str, price: Decimal, qty: Decimal) -> Order:
        with self._get_session() as session:
            existing = self._find_active_order(session, position.id, role)
            if existing and self._matches(existing, "sell" if position.side == "long" else "buy", price, None, qty):
                return existing
            side = "sell" if position.side == "long" else "buy"
            order = existing or Order(
                client_order_id=self._generate_client_order_id(position.id, role, position.decision_id),
                role=role,
                side=side,
                order_type="limit",
                status="new",
                decision_id=position.decision_id,
                position_id=position.id,
                symbol=self.symbol,
            )
            self._sync_core_fields(
                order,
                side=side,
                role=role,
                price=price,
                stop_price=None,
                orig_qty=qty,
                order_type="limit",
                decision_id=position.decision_id,
                position_id=position.id,
            )
            return self.place_or_update(order, session=session)

    def _update_order_after_exchange(self, order: Order, response) -> None:
        with self._get_session() as session:
            db_order = session.get(Order, order.id)
            if not db_order:
                db_order = order
                session.add(db_order)
            db_order.exchange_order_id = response.get("orderId") if isinstance(response, dict) else None
            db_order.status = response.get("status", "working") if isinstance(response, dict) else "working"
            db_order.created_at_utc = db_order.created_at_utc or datetime.utcnow()
            db_order.updated_at_utc = datetime.utcnow()
            session.commit()
            session.refresh(db_order)
            order.id = db_order.id
            order.exchange_order_id = db_order.exchange_order_id
            order.status = db_order.status

    @staticmethod
    def _matches(
        order: Order,
        side: str,
        price: Optional[Decimal],
        stop_price: Optional[Decimal],
        orig_qty: Decimal,
    ) -> bool:
        def _as_dec(val):
            return Decimal(str(val)) if val is not None else None

        return (
            order.side == side
            and _as_dec(order.price) == _as_dec(price)
            and _as_dec(order.stop_price) == _as_dec(stop_price)
            and Decimal(str(order.orig_qty)) == Decimal(str(orig_qty))
        )
