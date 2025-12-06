import time
from typing import Dict, Any

import time
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config_loader import load_config


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get_initial_equity() -> float:
    cfg = load_config()
    return float(cfg.get("trading", {}).get("initial_equity_usd", 10000.0))


def load_state(db: Session) -> Dict[str, Any]:
    """
    Загружает состояние бота из таблицы bot_state (id=1).
    Если записи нет — создаёт её с дефолтными значениями.
    """
    stmt = text("SELECT * FROM bot_state WHERE id = :id")
    row = db.execute(stmt, {"id": 1}).mappings().first()

    if row is None:
        state = {
            "id": 1,
            "position": "NONE",
            "entry_price": None,
            "entry_time": None,
            "qty": 0.0,
            "stop_loss": None,
            "take_profit": None,
            "equity": _get_initial_equity(),
            "updated_at": _now_ms(),
        }

        insert_stmt = text(
            """
            INSERT INTO bot_state (
                id, position, entry_price, entry_time, qty,
                stop_loss, take_profit, equity, updated_at
            ) VALUES (
                :id, :position, :entry_price, :entry_time, :qty,
                :stop_loss, :take_profit, :equity, :updated_at
            )
            """
        )
        db.execute(insert_stmt, state)
        db.commit()
        return state

    return dict(row)


def save_state(db: Session, state: Dict[str, Any]) -> None:
    """
    Обновляет текущее состояние бота (id=1).
    """
    # Гарантируем наличие всех ключей
    defaults = {
        "position": "NONE",
        "entry_price": None,
        "entry_time": None,
        "qty": 0.0,
        "stop_loss": None,
        "take_profit": None,
        "equity": _get_initial_equity(),
        "updated_at": _now_ms(),
    }
    for k, v in defaults.items():
        state.setdefault(k, v)

    state["id"] = 1

    update_stmt = text(
        """
        UPDATE bot_state
        SET
            position = :position,
            entry_price = :entry_price,
            entry_time = :entry_time,
            qty = :qty,
            stop_loss = :stop_loss,
            take_profit = :take_profit,
            equity = :equity,
            updated_at = :updated_at
        WHERE id = :id
        """
    )

    db.execute(update_stmt, state)
    db.commit()
