"""Helpers for consistent structured logging across the project."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping


def _serialize(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit a JSON-encoded log entry with a fixed ``event`` field."""
    payload = {"event": event, **fields}
    logger.log(level, _serialize(payload))


def log_info(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.INFO, event, **fields)


def log_warning(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.WARNING, event, **fields)


def log_error(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.ERROR, event, **fields)
