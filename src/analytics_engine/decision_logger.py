"""
Logging helper for persisting decisions to the database using the
current SQLAlchemy models.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

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
        timestamp=now_ms,
        created_at=datetime.utcnow(),
        action=action,
        reason=decision.get("reason") or decision.get("rationale"),
        entry_min_price=_as_decimal(decision.get("entry_min_price") or price_ref),
        entry_max_price=_as_decimal(decision.get("entry_max_price") or price_ref),
        sl_price=_as_decimal(decision.get("sl_price") or decision.get("stop_loss")),
        tp1_price=_as_decimal(decision.get("tp1_price") or decision.get("take_profit")),
        tp2_price=_as_decimal(decision.get("tp2_price")),
        position_size_usdt=_as_decimal(
            decision.get("position_size_usdt") or decision.get("position_size")
        ),
        leverage=decision.get("leverage"),
        risk_level=int(decision.get("risk_level") or 0),
        confidence=float(decision.get("confidence") or 0.0),
        risk_checks_json=decision.get("risk_checks")
        or decision.get("risk_flags")
        or decision.get("risk_checks_json"),
        snapshot_id=decision.get("snapshot_id"),
        flow_id=decision.get("flow_id"),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "Decision saved: id=%s action=%s conf=%.3f reason=%s",
        row.id,
        row.action,
        row.confidence,
        row.reason,
    )

    return row.id

