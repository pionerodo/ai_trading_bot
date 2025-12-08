"""
v1 – простой бумажный Execution Engine:

- читает:
    - data/btc_snapshot.json
    - data/btc_flow.json
    - data/decision.json
- смотрит текущее состояние в таблице bot_state
- если позиции нет и решение "long"/"short" с достаточной уверенностью:
    - создаёт запись в executions (статус PLANNED)
    - обновляет bot_state (позиция LONG/SHORT)

Никаких реальных ордеров на Binance здесь НЕТ.
Это подготовка структуры исполнения и проверка связки Decision → Execution.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# --- Пути проекта и импорт DB utils ---

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection

LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "execution_engine.log")

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "btc_snapshot.json")
FLOW_PATH = os.path.join(DATA_DIR, "btc_flow.json")
DECISION_PATH = os.path.join(DATA_DIR, "decision.json")

SYMBOL_DB = "BTCUSDT"

# --- Простые константы v1 ---

# Минимальная уверенность, чтобы попытаться открыть сделку
MIN_CONFIDENCE = 0.55

# Фиксированный номинал на сделку (бумажный режим), в USDT
NOTIONAL_PER_TRADE = 100.0

logger = logging.getLogger(__name__)


# --- Логирование ---

def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        fh = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


# --- JSON helpers ---

def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        logger.error("execution_engine: file not found: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("execution_engine: failed to load %s: %s", path, e, exc_info=True)
        return None


# --- DB helpers ---

def get_bot_state(conn) -> Dict[str, Any]:
    """
    Читаем состояние бота из bot_state.
    Если строки нет — создаём дефолтную.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, position, entry_price, entry_time, qty, stop_loss, take_profit, equity, updated_at FROM bot_state WHERE id = 1"
        )
        row = cur.fetchone()

        if row:
            return {
                "id": int(row[0]),
                "position": row[1],
                "entry_price": row[2],
                "entry_time": row[3],
                "qty": row[4],
                "stop_loss": row[5],
                "take_profit": row[6],
                "equity": row[7],
                "updated_at": row[8],
            }

        logger.info("execution_engine: bot_state row not found, inserting default")
        cur.execute(
            """
            INSERT INTO bot_state (id, position, entry_price, entry_time, qty, stop_loss, take_profit, equity, updated_at)
            VALUES (1, 'NONE', NULL, NULL, NULL, NULL, NULL, 10000.0, NULL)
            """
        )
        conn.commit()

        return {
            "id": 1,
            "position": "NONE",
            "entry_price": None,
            "entry_time": None,
            "qty": None,
            "stop_loss": None,
            "take_profit": None,
            "equity": 10000.0,
            "updated_at": None,
        }


def update_bot_state_on_entry(
    conn,
    side: str,
    price: float,
    qty: float,
    ts_ms: int,
) -> None:
    """
    Обновляем bot_state при открытии новой позиции (бумажно).
    side: 'LONG' / 'SHORT'
    """
    now_ms = ts_ms
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bot_state
            SET position=%s,
                entry_price=%s,
                entry_time=%s,
                qty=%s,
                updated_at=%s
            WHERE id=1
            """,
            (side, price, now_ms, qty, now_ms),
        )
    conn.commit()


def insert_execution_row(
    conn,
    ts_ms: int,
    symbol: str,
    side: str,
    price: float,
    qty: float,
    status: str,
    decision: Dict[str, Any],
) -> int:
    """
    Пишем строку в executions.

    status v1: 'PLANNED'
    side: 'LONG' / 'SHORT'
    """
    json_data = json.dumps(
        {
            "type": "entry",
            "mode": "paper",
            "decision": decision,
        },
        ensure_ascii=False,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO executions (
                timestamp_ms,
                symbol,
                side,
                price,
                qty,
                status,
                order_id,
                json_data
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (ts_ms, symbol, side, price, qty, status, None, json_data),
        )
        exec_id = cur.lastrowid

    conn.commit()
    return int(exec_id)


# --- Основная логика решения "открывать / не открывать" ---

def should_open_position(
    bot_state: Dict[str, Any],
    decision: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Простое правило v1:
    - если уже есть позиция (position != 'NONE') → не входим
    - если decision.action не 'long'/'short' → не входим
    - если confidence < MIN_CONFIDENCE → не входим
    """
    pos = (bot_state.get("position") or "NONE").upper()
    action = (decision.get("action") or "flat").lower()
    confidence = float(decision.get("confidence") or 0.0)

    if pos != "NONE":
        return False, f"position_already_open ({pos})"

    if action not in ("long", "short"):
        return False, f"no_trade_action ({action})"

    if confidence < MIN_CONFIDENCE:
        return False, f"low_confidence ({confidence:.3f} < {MIN_CONFIDENCE:.3f})"

    return True, "ok"


def calc_order_params(
    decision: Dict[str, Any],
    bot_state: Dict[str, Any],
) -> Tuple[str, float, float, int]:
    """
    Вычисляем:
    - side: 'LONG'/'SHORT'
    - price: float (берём из decision.price)
    - qty: фиксированный номинал NOTIONAL_PER_TRADE / price
    - ts_ms: decision.timestamp_ms (fallback: now)
    """
    action = decision.get("action", "flat").lower()
    side = "LONG" if action == "long" else "SHORT"

    price = float(decision.get("price") or 0.0)
    if price <= 0:
        raise RuntimeError("execution_engine: invalid price in decision")

    ts_ms = int(decision.get("timestamp_ms") or int(datetime.now(timezone.utc).timestamp() * 1000))

    qty = NOTIONAL_PER_TRADE / price
    qty = float(f"{qty:.6f}")

    return side, price, qty, ts_ms


# --- main ---

def main() -> None:
    setup_logging()
    logger.info("execution_engine: started")

    snapshot = load_json(SNAPSHOT_PATH)
    if not snapshot:
        logger.error("execution_engine: snapshot file missing/invalid: %s", SNAPSHOT_PATH)
        sys.exit(1)

    flow = load_json(FLOW_PATH)
    if not flow:
        logger.error("execution_engine: flow file missing/invalid: %s", FLOW_PATH)
        sys.exit(1)

    decision = load_json(DECISION_PATH)
    if not decision:
        logger.error("execution_engine: decision file missing/invalid: %s", DECISION_PATH)
        sys.exit(1)

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("execution_engine: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        bot_state = get_bot_state(conn)
        ok, reason = should_open_position(bot_state, decision)

        if not ok:
            logger.info("execution_engine: no new position, reason=%s", reason)
            return

        side, price, qty, ts_ms = calc_order_params(decision, bot_state)

        exec_id = insert_execution_row(
            conn=conn,
            ts_ms=ts_ms,
            symbol=SYMBOL_DB,
            side=side,
            price=price,
            qty=qty,
            status="PLANNED",
            decision=decision,
        )

        update_bot_state_on_entry(
            conn=conn,
            side=side,
            price=price,
            qty=qty,
            ts_ms=ts_ms,
        )

        logger.info(
            "execution_engine: planned %s entry (exec_id=%s, qty=%.6f, price=%.2f, reason=%s)",
            side,
            exec_id,
            qty,
            price,
            decision.get("reason"),
        )

    except Exception as e:
        logger.error("execution_engine: failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("execution_engine: finished")


if __name__ == "__main__":
    main()
