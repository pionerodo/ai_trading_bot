import time
import logging
from typing import Dict, Any

from sqlalchemy.orm import Session

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
        json_data=decision
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "Decision saved: id=%s action=%s conf=%.3f reason=%s",
        row.id,
        decision.get("action"),
        decision.get("confidence"),
        decision.get("reason"),
    )

    return row.id
