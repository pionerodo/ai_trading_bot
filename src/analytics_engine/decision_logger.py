import logging
import time
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.metrics import increment_metric
from src.core.structured_logging import log_error, log_info
from src.db.models import Decision


logger = logging.getLogger("ai_trading_bot")


def log_decision(db: Session, symbol: str, decision: Dict[str, Any]) -> int:
    """
    Сохраняет решение в таблицу decisions.
    Возвращает ID записи.
    """
    now_ms = int(time.time() * 1000)

    row = Decision(
        timestamp_ms=now_ms,
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
