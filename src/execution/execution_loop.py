import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from src.db.models import Decision, LiquidationZone, Position, Snapshot
from src.execution.execution_logger import log_execution_event, log_risk_event
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager
from src.execution.risk_checks import evaluate_local_entry_risk

logger = logging.getLogger(__name__)


def load_latest_decision_for_symbol(db_session_factory, symbol: str = "BTCUSDT") -> Optional[dict]:
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    with db_session_factory() as session:  # type: Session
        row = (
            session.query(Decision)
            .filter(
                Decision.symbol == symbol,
                Decision.action.in_(["long", "short"]),
                Decision.created_at >= cutoff,
            )
            .order_by(Decision.created_at.desc())
            .first()
        )
        if not row:
            return None

        entry_price = row.entry_max_price
        if row.entry_min_price is not None and row.entry_max_price is not None:
            entry_price = (row.entry_min_price + row.entry_max_price) / 2
        elif row.entry_min_price is not None:
            entry_price = row.entry_min_price
        elif row.entry_max_price is not None:
            entry_price = row.entry_max_price

        return {
            "id": row.id,
            "decision_id": row.id,
            "side": row.action,
            "action": row.action,
            "symbol": row.symbol,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "entry_min_price": float(row.entry_min_price) if row.entry_min_price else None,
            "entry_max_price": float(row.entry_max_price) if row.entry_max_price else None,
            "sl_price": float(row.sl_price) if row.sl_price else None,
            "tp1_price": float(row.tp1_price) if row.tp1_price else None,
            "tp2_price": float(row.tp2_price) if row.tp2_price else None,
            "position_size": float(row.position_size_usdt)
            if row.position_size_usdt is not None
            else None,
            "leverage": float(row.leverage) if row.leverage is not None else None,
            "risk_mode": row.risk_level,
            "position_management_json": None,
            "created_at": row.created_at,
        }


def load_latest_price_for_symbol(db_session_factory, symbol: str = "BTCUSDT") -> Optional[Decimal]:
    """
    Load the latest price for the symbol from the snapshots table.
    """
    with db_session_factory() as session:  # type: Session
        row = (
            session.query(Snapshot)
            .filter(Snapshot.symbol == symbol)
            .order_by(Snapshot.timestamp.desc())
            .first()
        )
        if not row:
            return None
        return _as_decimal(row.price)


def load_linked_decision_and_liq_zone(
    db_session_factory, position
) -> Tuple[Optional[Decision], Optional[LiquidationZone]]:
    """
    Load the linked decision and its referenced liquidation zone (if any).
    """
    if not position or position.decision_id is None:
        return None, None

    with db_session_factory() as session:  # type: Session
        decision = session.get(Decision, position.decision_id)
        if not decision:
            return None, None

        if not decision.liq_tp_zone_id:
            return decision, None

        liq_zone = (
            session.query(LiquidationZone)
            .filter(
                LiquidationZone.symbol == position.symbol,
                LiquidationZone.cluster_id == decision.liq_tp_zone_id,
            )
            .order_by(LiquidationZone.captured_at_utc.desc())
            .first()
        )
        return decision, liq_zone


def move_sl_to_breakeven_if_needed(
    position_manager: PositionManager, position
):
    """
    Ensure SL is at least at breakeven after TP1. Does not widen risk.
    """
    if position.status != "open":
        return position

    entry_price = _as_decimal(position.entry_price)
    current_sl = _as_decimal(position.sl_price) if position.sl_price is not None else None

    if position.side == "long":
        new_sl = entry_price if current_sl is None else max(current_sl, entry_price)
        if current_sl is None or new_sl > current_sl:
            updated = position_manager.update_sl_tp(position.id, sl_price=float(new_sl))
            logger.info(
                "Moved SL to breakeven/better for long position %s: old=%s new=%s",
                position.id,
                current_sl,
                new_sl,
            )
            return updated
    else:
        new_sl = entry_price if current_sl is None else min(current_sl, entry_price)
        if current_sl is None or new_sl < current_sl:
            updated = position_manager.update_sl_tp(position.id, sl_price=float(new_sl))
            logger.info(
                "Moved SL to breakeven/better for short position %s: old=%s new=%s",
                position.id,
                current_sl,
                new_sl,
            )
            return updated

    return position


def apply_trailing_sl(
    position_manager: PositionManager,
    position,
    current_price: Decimal,
    decision: Optional[Decision] = None,
    liq_zone: Optional[LiquidationZone] = None,
):
    """
    Apply a simple trailing SL when TP1 is hit. Never widens SL and keeps it
    at/inside breakeven. Tightens more aggressively when near a referenced
    liquidation zone.
    """

    if position.status != "open" or not position.tp1_hit:
        return

    config = _parse_position_management(position.position_management_json)
    trailing_mode = config.get("trailing_mode") or config.get("trailing")
    if trailing_mode and trailing_mode != "structure_plus_liq":
        return

    trail_pct = Decimal(str(config.get("trail_pct", 0.005)))
    activation_rr = Decimal(str(config.get("trail_activation_rr", 1.0)))
    entry_price = _as_decimal(position.entry_price)
    current_sl = _as_decimal(position.sl_price) if position.sl_price is not None else None

    # Optional activation: only trail after RR threshold beyond entry
    if activation_rr > 0 and entry_price > 0:
        rr_move = (current_price - entry_price) / entry_price if position.side == "long" else (entry_price - current_price) / entry_price
        if rr_move < activation_rr:
            return

    if liq_zone is not None:
        zone_price = _as_decimal(liq_zone.price_level)
        if position.side == "long" and current_price >= zone_price * Decimal("0.99"):
            trail_pct = min(trail_pct, Decimal("0.003"))
        if position.side == "short" and current_price <= zone_price * Decimal("1.01"):
            trail_pct = min(trail_pct, Decimal("0.003"))

    if position.side == "long":
        candidate_sl = current_price * (Decimal("1") - trail_pct)
        candidate_sl = max(candidate_sl, entry_price)
        if current_sl is None or candidate_sl > current_sl:
            updated = position_manager.update_sl_tp(position.id, sl_price=float(candidate_sl))
            logger.info(
                "Trailing SL tightened for long position %s: old=%s new=%s price=%s trail_pct=%s",
                position.id,
                current_sl,
                candidate_sl,
                current_price,
                trail_pct,
            )
            return updated
    else:
        candidate_sl = current_price * (Decimal("1") + trail_pct)
        candidate_sl = min(candidate_sl, entry_price)
        if current_sl is None or candidate_sl < current_sl:
            updated = position_manager.update_sl_tp(position.id, sl_price=float(candidate_sl))
            logger.info(
                "Trailing SL tightened for short position %s: old=%s new=%s price=%s trail_pct=%s",
                position.id,
                current_sl,
                candidate_sl,
                current_price,
                trail_pct,
            )
            return updated


def _parse_position_management(position_management_json):
    if position_management_json is None:
        return {}
    if isinstance(position_management_json, dict):
        return position_management_json
    try:
        return json.loads(position_management_json)
    except Exception:
        return {}


def run_single_cycle(db_session_factory, symbol: str = "BTCUSDT") -> None:
    position_manager = PositionManager(db_session_factory, symbol=symbol)
    order_manager = OrderManager(db_session_factory, symbol=symbol)

    open_position = position_manager.get_open_position()
    decision = load_latest_decision_for_symbol(db_session_factory, symbol=symbol)

    if open_position is None:
        if decision is None:
            logger.info("No open position and no new decision for %s", symbol)
            return

        risk_result = evaluate_local_entry_risk(decision)
        if not risk_result.allow_entry:
            logger.warning(
                "Decision %s rejected by local risk: %s",
                decision.get("decision_id"),
                "; ".join(risk_result.reasons),
            )
            log_risk_event(
                db_session_factory,
                event_type="ENTRY_REJECTED_LOCAL_RISK",
                symbol=symbol,
                details="; ".join(risk_result.reasons),
                extra={
                    "decision_id": decision.get("decision_id"),
                    "sl_price": decision.get("sl_price"),
                    "tp1_price": decision.get("tp1_price"),
                    "tp2_price": decision.get("tp2_price"),
                    "reasons": risk_result.reasons,
                },
            )
            return

        position = position_manager.create_from_decision(decision)
        entry_order = order_manager.build_entry_order(position, decision)
        sl_order = order_manager.build_sl_order(position) if position.sl_price else None
        tp1_order, tp2_order = order_manager.build_tp_orders(position)

        order_manager.place_or_update(entry_order)
        if sl_order:
            order_manager.place_or_update(sl_order)
        if tp1_order:
            order_manager.place_or_update(tp1_order)
        if tp2_order:
            order_manager.place_or_update(tp2_order)

        logger.info(
            "Position %s created with entry order %s (sl=%s tp1=%s tp2=%s)",
            position.id,
            entry_order.id,
            sl_order.id if sl_order else None,
            tp1_order.id if tp1_order else None,
            tp2_order.id if tp2_order else None,
        )
        return

    current_price = load_latest_price_for_symbol(db_session_factory, symbol)
    if current_price is None:
        logger.warning("No latest price for %s, skipping exit checks", symbol)
        return

    sl = _as_decimal(open_position.sl_price) if open_position.sl_price is not None else None
    tp1 = _as_decimal(open_position.tp1_price) if open_position.tp1_price is not None else None
    tp2 = _as_decimal(open_position.tp2_price) if open_position.tp2_price is not None else None

    logger.info(
        "Evaluating exits for position %s side=%s price=%s sl=%s tp1=%s tp2=%s tp1_hit=%s",
        open_position.id,
        open_position.side,
        current_price,
        sl,
        tp1,
        tp2,
        open_position.tp1_hit,
    )

    # Exit check order: SL -> TP2 -> TP1 -> liquidation-based exit -> trailing/BE adjustments
    if open_position.side == "long":
        if sl is not None and current_price <= sl:
            position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="sl",
            )
            logger.info(
                "Closed long position %s via SL at price %s", open_position.id, current_price
            )
            return

        if tp2 is not None and current_price >= tp2:
            position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="tp2",
            )
            logger.info(
                "Closed long position %s via TP2 at price %s", open_position.id, current_price
            )
            return

        if (not open_position.tp1_hit) and tp1 is not None and current_price >= tp1:
            open_position = position_manager.mark_tp1_hit(
                open_position.id, price=current_price, ts_utc=datetime.utcnow()
            )
            logger.info(
                "Marked TP1 hit for long position %s at price %s", open_position.id, current_price
            )
            open_position = move_sl_to_breakeven_if_needed(position_manager, open_position)
    else:  # short
        if sl is not None and current_price >= sl:
            position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="sl",
            )
            logger.info(
                "Closed short position %s via SL at price %s", open_position.id, current_price
            )
            return

        if tp2 is not None and current_price <= tp2:
            position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="tp2",
            )
            logger.info(
                "Closed short position %s via TP2 at price %s", open_position.id, current_price
            )
            return

        if (not open_position.tp1_hit) and tp1 is not None and current_price <= tp1:
            open_position = position_manager.mark_tp1_hit(
                open_position.id, price=current_price, ts_utc=datetime.utcnow()
            )
            logger.info(
                "Marked TP1 hit for short position %s at price %s", open_position.id, current_price
            )
            open_position = move_sl_to_breakeven_if_needed(position_manager, open_position)

    decision, liq_zone = load_linked_decision_and_liq_zone(db_session_factory, open_position)
    if liq_zone is not None and open_position.status == "open":
        zone_price = _as_decimal(liq_zone.price_level)

        if open_position.side == "long" and current_price <= zone_price:
            pm_close, _ = position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="liq_exit",
            )
            with db_session_factory() as session:  # type: Session
                db_pos = session.get(Position, pm_close.id)
                if db_pos:
                    db_pos.liq_exit_used = True
                    session.commit()

            order_manager.cancel_stale_for_position(open_position.id)
            logger.info(
                "Liq-exit triggered for long position %s (cluster=%s zone=%s current=%s)",
                open_position.id,
                liq_zone.cluster_id,
                zone_price,
                current_price,
            )
            log_execution_event(
                db_session_factory,
                module="execution_loop",
                level="INFO",
                message="POSITION_LIQ_EXIT",
                context={
                    "position_id": open_position.id,
                    "symbol": symbol,
                    "side": open_position.side,
                    "decision_id": open_position.decision_id,
                    "cluster_id": liq_zone.cluster_id,
                    "zone_price": float(zone_price),
                    "current_price": float(current_price),
                },
            )
            return

        if open_position.side == "short" and current_price >= zone_price:
            pm_close, _ = position_manager.close_position(
                open_position.id,
                exit_price=current_price,
                ts_utc=datetime.utcnow(),
                exit_reason="liq_exit",
            )
            with db_session_factory() as session:  # type: Session
                db_pos = session.get(Position, pm_close.id)
                if db_pos:
                    db_pos.liq_exit_used = True
                    session.commit()

            order_manager.cancel_stale_for_position(open_position.id)
            logger.info(
                "Liq-exit triggered for short position %s (cluster=%s zone=%s current=%s)",
                open_position.id,
                liq_zone.cluster_id,
                zone_price,
                current_price,
            )
            log_execution_event(
                db_session_factory,
                module="execution_loop",
                level="INFO",
                message="POSITION_LIQ_EXIT",
                context={
                    "position_id": open_position.id,
                    "symbol": symbol,
                    "side": open_position.side,
                    "decision_id": open_position.decision_id,
                    "cluster_id": liq_zone.cluster_id,
                    "zone_price": float(zone_price),
                    "current_price": float(current_price),
                },
            )
            return

    if open_position.status == "open" and open_position.tp1_hit:
        open_position = move_sl_to_breakeven_if_needed(position_manager, open_position)
        apply_trailing_sl(
            position_manager,
            open_position,
            current_price,
            decision=decision,
            liq_zone=liq_zone,
        )

    logger.info("Position %s remains open after exit checks", open_position.id)


def run_loop(
    db_session_factory,
    symbol: str = "BTCUSDT",
    max_seconds: float = 3.0,
    sleep_seconds: float = 1.0,
) -> None:
    start = time.time()
    while True:
        run_single_cycle(db_session_factory, symbol=symbol)
        if time.time() - start >= max_seconds:
            break
        time.sleep(sleep_seconds)


def _as_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")
