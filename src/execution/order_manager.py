import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from src.db.models import Order, Position

logger = logging.getLogger(__name__)


_ACTIVE_STATUSES = ("new", "working")
_FILLED_STATUSES = ("filled",)


class OrderManager:
    def __init__(self, db_session_factory, symbol: str = "BTCUSDT"):
        self.db_session_factory = db_session_factory
        self.symbol = symbol

    def _get_session(self) -> Session:
        return self.db_session_factory()

    def _generate_client_order_id(self, position_id: int, role: str, decision_id: Optional[int]) -> str:
        ts = int(datetime.utcnow().timestamp() * 1000)
        decision_part = f"{decision_id}" if decision_id is not None else "na"
        return f"{self.symbol}-{position_id}-{role}-{decision_part}-{ts}"

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
            if existing and self._matches(existing, side, price_dec, None, Decimal(str(position.size))):
                return existing

            if existing:
                logger.info(
                    "Updating existing entry order %s for position %s", existing.id, position.id
                )
                self._sync_core_fields(
                    existing,
                    side=side,
                    role=role,
                    price=price_dec,
                    stop_price=None,
                    orig_qty=Decimal(str(position.size)),
                    order_type=order_type,
                    decision_id=decision_id,
                    position_id=position.id,
                )
                return self.place_or_update(existing, session=session)

            order = Order(
                client_order_id=self._generate_client_order_id(position.id, role, decision_id),
                role=role,
                side=side,
                order_type=order_type,
                status="new",
                price=price_dec,
                stop_price=None,
                orig_qty=Decimal(str(position.size)),
                executed_qty=Decimal("0"),
                avg_fill_price=None,
                decision_id=decision_id,
                position_id=position.id,
                symbol=self.symbol,
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
            if existing and self._matches(existing, side, None, stop_price, Decimal(str(position.size))):
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
                orig_qty=Decimal(str(position.size)),
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
