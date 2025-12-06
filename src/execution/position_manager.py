import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from src.db.models import Position, Trade
from src.execution.execution_logger import log_execution_event, log_risk_event

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self, db_session_factory, symbol: str = "BTCUSDT"):
        self.db_session_factory = db_session_factory
        self.symbol = symbol

    def _get_session(self) -> Session:
        return self.db_session_factory()

    def get_open_position(self) -> Optional[Position]:
        """
        Return the current open position for the symbol (status='open'),
        or None if there is no open position.
        """
        with self._get_session() as session:
            return (
                session.query(Position)
                .filter(
                    Position.symbol == self.symbol,
                    Position.status == "open",
                )
                .order_by(Position.opened_at_utc.desc())
                .first()
            )

    def create_from_decision(self, decision: dict) -> Position:
        """
        Create a new position row from a validated decision payload.
        Raises if there is already an open position for this symbol.
        """
        with self._get_session() as session:
            existing = (
                session.query(Position)
                .filter(Position.symbol == self.symbol, Position.status == "open")
                .first()
            )
            if existing:
                raise ValueError(f"Open position already exists for {self.symbol} (id={existing.id})")

            side = decision.get("side") or decision.get("action")
            if side not in {"long", "short"}:
                raise ValueError("Decision missing side (expected 'long' or 'short')")

            entry_price = decision.get("entry_price") or decision.get("avg_entry_price")
            if entry_price is None:
                raise ValueError("Decision missing entry_price/avg_entry_price")

            avg_entry_price = decision.get("avg_entry_price") or entry_price

            size = decision.get("size") or decision.get("position_size")
            if size is None:
                raise ValueError("Decision missing size/position_size")

            position = Position(
                symbol=self.symbol,
                side=side,
                status="open",
                entry_price=entry_price,
                avg_entry_price=avg_entry_price,
                size=size,
                max_size=decision.get("max_size") or size,
                sl_price=decision.get("sl_price"),
                tp1_price=decision.get("tp1_price"),
                tp2_price=decision.get("tp2_price"),
                opened_at_utc=datetime.utcnow(),
                risk_mode_at_open=decision.get("risk_mode") or decision.get("risk_mode_at_open"),
                decision_id=decision.get("decision_id") or decision.get("id"),
                position_management_json=decision.get("position_management_json"),
            )

            session.add(position)
            session.commit()
            session.refresh(position)

            logger.info(
                "Position created from decision %s: id=%s side=%s size=%s entry=%s sl=%s tp1=%s tp2=%s",
                position.decision_id,
                position.id,
                position.side,
                position.size,
                position.entry_price,
                position.sl_price,
                position.tp1_price,
                position.tp2_price,
            )
            log_execution_event(
                self.db_session_factory,
                module="position_manager",
                level="INFO",
                message="POSITION_OPEN",
                context={
                    "position_id": position.id,
                    "decision_id": position.decision_id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "entry_price": float(position.entry_price),
                    "sl_price": float(position.sl_price) if position.sl_price else None,
                    "tp1_price": float(position.tp1_price) if position.tp1_price else None,
                    "tp2_price": float(position.tp2_price) if position.tp2_price else None,
                    "risk_mode_at_open": position.risk_mode_at_open,
                },
            )
            return position

    def mark_tp1_hit(self, position_id: int, price: float, ts_utc: datetime) -> Position:
        with self._get_session() as session:
            position = session.get(Position, position_id)
            if not position or position.symbol != self.symbol:
                raise ValueError(f"Position {position_id} not found for symbol {self.symbol}")

            position.tp1_hit = True
            position.tp1_price = position.tp1_price or price

            session.commit()
            session.refresh(position)

            logger.info(
                "TP1 marked for position %s at price=%s time=%s", position.id, price, ts_utc
            )
            log_execution_event(
                self.db_session_factory,
                module="position_manager",
                level="INFO",
                message="POSITION_TP1_HIT",
                context={
                    "position_id": position.id,
                    "symbol": position.symbol,
                    "price": float(price),
                    "tp1_price": float(position.tp1_price) if position.tp1_price else None,
                    "tp1_hit": position.tp1_hit,
                },
            )
            return position

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        ts_utc: datetime,
        exit_reason: str,
    ) -> Tuple[Position, Trade]:
        with self._get_session() as session:
            position = session.get(Position, position_id)
            if not position or position.symbol != self.symbol:
                raise ValueError(f"Position {position_id} not found for symbol {self.symbol}")

            entry_price = self._as_decimal(position.avg_entry_price or position.entry_price)
            exit_price_dec = self._as_decimal(exit_price)
            size = self._as_decimal(position.size)

            pnl_usdt = self._calculate_pnl(entry_price, exit_price_dec, size, position.side)
            notional = entry_price * size if entry_price and size else Decimal("0")
            pnl_pct = (pnl_usdt / notional * Decimal("100")) if notional else Decimal("0")

            position.status = "closed"
            position.closed_at_utc = ts_utc
            position.pnl_usdt = pnl_usdt
            position.pnl_pct = pnl_pct

            trade = Trade(
                position_id=position.id,
                decision_id=position.decision_id,
                symbol=position.symbol,
                side=position.side,
                entry_price=position.entry_price,
                avg_entry_price=position.avg_entry_price,
                exit_price=exit_price,
                avg_exit_price=exit_price,
                quantity=position.size,
                pnl_usdt=pnl_usdt,
                pnl_pct=pnl_pct,
                opened_at_utc=position.opened_at_utc,
                closed_at_utc=ts_utc,
                exit_reason=exit_reason,
                tp1_hit=bool(position.tp1_hit),
                tp2_hit=bool(position.tp2_hit),
                position_management_json=position.position_management_json,
            )

            session.add(trade)
            session.commit()
            session.refresh(position)
            session.refresh(trade)

            logger.info(
                "Position %s closed with reason=%s exit_price=%s pnl_usdt=%s pnl_pct=%s",
                position.id,
                exit_reason,
                exit_price,
                pnl_usdt,
                pnl_pct,
            )
            log_execution_event(
                self.db_session_factory,
                module="position_manager",
                level="INFO",
                message="POSITION_CLOSE",
                context={
                    "position_id": position.id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "exit_reason": exit_reason,
                    "entry_price": float(position.entry_price),
                    "exit_price": float(exit_price),
                    "pnl_usdt": float(pnl_usdt),
                    "pnl_pct": float(pnl_pct),
                },
            )

            return position, trade

    def update_sl_tp(
        self,
        position_id: int,
        sl_price: Optional[float] = None,
        tp1_price: Optional[float] = None,
        tp2_price: Optional[float] = None,
    ) -> Position:
        with self._get_session() as session:
            position = session.get(Position, position_id)
            if not position or position.symbol != self.symbol:
                raise ValueError(f"Position {position_id} not found for symbol {self.symbol}")

            entry_price = self._as_decimal(position.entry_price)
            current_sl = self._as_decimal(position.sl_price) if position.sl_price else None
            min_distance = entry_price * Decimal("0.0035")
            initial_sl = position.sl_price

            if sl_price is not None:
                new_sl = self._as_decimal(sl_price)
                if position.side == "long":
                    if current_sl is not None and new_sl < current_sl:
                        log_risk_event(
                            self.db_session_factory,
                            event_type="SL_EXPANSION_BLOCKED",
                            symbol=self.symbol,
                            details="Attempted to widen SL on long position",
                            extra={"position_id": position.id, "current_sl": float(current_sl), "new_sl": float(new_sl)},
                        )
                    elif new_sl >= entry_price:
                        position.sl_price = new_sl
                    elif entry_price - new_sl < min_distance:
                        logger.warning(
                            "Rejecting SL too close to entry for position %s: entry=%s new_sl=%s min_dist=%s",
                            position.id,
                            entry_price,
                            new_sl,
                            min_distance,
                        )
                    else:
                        position.sl_price = new_sl
                else:  # short
                    if current_sl is not None and new_sl > current_sl:
                        log_risk_event(
                            self.db_session_factory,
                            event_type="SL_EXPANSION_BLOCKED",
                            symbol=self.symbol,
                            details="Attempted to widen SL on short position",
                            extra={"position_id": position.id, "current_sl": float(current_sl), "new_sl": float(new_sl)},
                        )
                    elif new_sl <= entry_price:
                        position.sl_price = new_sl
                    elif new_sl - entry_price < min_distance:
                        logger.warning(
                            "Rejecting SL too close to entry for position %s: entry=%s new_sl=%s min_dist=%s",
                            position.id,
                            entry_price,
                            new_sl,
                            min_distance,
                        )
                    else:
                        position.sl_price = new_sl

            if tp1_price is not None:
                position.tp1_price = tp1_price
            if tp2_price is not None:
                position.tp2_price = tp2_price

            session.commit()
            session.refresh(position)

            logger.info(
                "Updated SL/TP for position %s: sl=%s tp1=%s tp2=%s",
                position.id,
                position.sl_price,
                position.tp1_price,
                position.tp2_price,
            )
            if initial_sl != position.sl_price and position.sl_price is not None:
                log_execution_event(
                    self.db_session_factory,
                    module="position_manager",
                    level="INFO",
                    message="SL_TIGHTENED",
                    context={
                        "position_id": position.id,
                        "symbol": position.symbol,
                        "old_sl": float(initial_sl) if initial_sl else None,
                        "new_sl": float(position.sl_price),
                    },
                )
            return position

    @staticmethod
    def _as_decimal(value) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal("0")

    @staticmethod
    def _calculate_pnl(entry: Decimal, exit: Decimal, size: Decimal, side: str) -> Decimal:
        if side == "long":
            return (exit - entry) * size
        return (entry - exit) * size
