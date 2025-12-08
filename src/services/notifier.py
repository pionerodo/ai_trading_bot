from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from sqlalchemy.orm import Session

from src.db.models import Notification

logger = logging.getLogger(__name__)


@dataclass
class NotifierConfig:
    enabled: bool = False
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class Notifier:
    """Persist notifications to the DB and optionally forward to Telegram."""

    def __init__(self, db: Session, cfg: NotifierConfig):
        self.db = db
        self.cfg = cfg

    def notify(
        self,
        *,
        title: str,
        message: str,
        level: str = "info",
        channel: str = "log",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        payload = Notification(
            level=level,
            channel=channel,
            title=title,
            message=message,
            meta=meta or {},
        )
        self.db.add(payload)
        self.db.commit()
        self.db.refresh(payload)

        if self.cfg.enabled and self.cfg.telegram_token and self.cfg.telegram_chat_id:
            self._send_telegram(message)

        logger.info("notification stored: %s/%s", level, title)
        return payload

    def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
        data = {"chat_id": self.cfg.telegram_chat_id, "text": message}
        try:
            resp = requests.post(url, data=data, timeout=5)
            if resp.status_code >= 400:
                logger.warning("telegram notification failed: %s", resp.text)
        except Exception as exc:  # pragma: no cover - network errors
            logger.warning("telegram notification error: %s", exc)
