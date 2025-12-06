import json
import logging
from datetime import datetime
from typing import Dict, Optional

from src.db.models import Log, RiskEvent

logger = logging.getLogger(__name__)


def _safe_dump(payload: Optional[Dict]) -> Optional[Dict]:
    if payload is None:
        return None
    try:
        json.dumps(payload)
        return payload
    except Exception:
        logger.warning("Failed to serialize context payload", exc_info=True)
        return None


def log_execution_event(
    db_session_factory,
    module: str,
    level: str,
    message: str,
    context: Optional[Dict] = None,
) -> None:
    """
    Persist a structured execution log into the logs table and emit to the standard logger.
    """

    level_upper = level.upper() if level else "INFO"
    log_fn = {
        "DEBUG": logger.debug,
        "INFO": logger.info,
        "WARNING": logger.warning,
        "ERROR": logger.error,
        "CRITICAL": logger.critical,
    }.get(level_upper, logger.info)

    log_fn("%s: %s", module, message)

    with db_session_factory() as session:
        row = Log(
            timestamp=datetime.utcnow(),
            level=level_upper,
            source=module,
            message=message,
            context=_safe_dump(context),
        )
        session.add(row)
        session.commit()


def log_risk_event(
    db_session_factory,
    event_type: str,
    symbol: str,
    details: str,
    extra: Optional[Dict] = None,
) -> None:
    """
    Persist a risk-related event into the risk_events table and emit to the standard logger.
    """

    logger.warning("%s: %s", event_type, details)

    with db_session_factory() as session:
        row = RiskEvent(
            timestamp=datetime.utcnow(),
            event_type=event_type,
            symbol=symbol,
            details=details,
            details_json=_safe_dump(extra),
        )
        session.add(row)
        session.commit()
