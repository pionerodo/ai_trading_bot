import logging
import time
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.metrics import increment_metric
from src.core.structured_logging import log_error, log_info
from src.db.models import Decision


logger = logging.getLogger("ai_trading_bot")


def _as_decimal(value: Optional[Any]) -> Optional[Decimal]:
    """Safely convert a value to Decimal or return ``None``."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def log_decision(db: Session, symbol: str, decision: Dict[str, Any]) -> int:
    """
    Persist a decision record into the ``decisions`` table.

    The previous implementation wrote legacy columns (``timestamp_ms`` and
    ``json_data``) that are no longer present in the current schema. This
    version maps incoming decision dictionaries onto the actual model fields
    such as ``timestamp``, price ranges, risk metadata and foreign keys.
    """

    now_ms = int(time.time() * 1000)
    action = (decision.get("action") or "").lower()
    if action not in {"long", "short", "flat"}:
        action = "flat"

    price_ref = _as_decimal(
        decision.get("price_ref")
        or decision.get("entry_price")
        or decision.get("price")
    )

    row = Decision(
        symbol=symbol,
        action=decision.get("action"),
        confidence=decision.get("confidence"),
        reason=decision.get("reason"),
        json_data=decision,
    )

    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        db.rollback()
        increment_metric(
            "decision_db_insert_failures",
            labels={"symbol": symbol, "action": str(decision.get("action"))},
        )
        log_error(
            logger,
            "decision_insert_failed",
            symbol=symbol,
            action=decision.get("action"),
            confidence=decision.get("confidence"),
            reason=decision.get("reason"),
            error=str(exc),
        )
        raise

    log_info(
        logger,
        "decision_saved",
        id=row.id,
        symbol=symbol,
        action=decision.get("action"),
        confidence=decision.get("confidence"),
        reason=decision.get("reason"),
    )

    return row.id

