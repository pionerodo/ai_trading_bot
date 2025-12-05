#!/usr/bin/env python3
"""
decision_engine.py

v2: Decision Engine с учётом ликвидационных метрик.

Что делает:
- читает:
    - data/btc_snapshot_v2.json
    - data/btc_flow.json
- на основе risk.mode и crowd.bias выбирает действие: long / short / flat
- корректирует confidence по ликвидациям (flow.liq_metrics)
- пишет:
    - data/decision.json
    - строку в таблицу decisions (idempotent по symbol+timestamp_ms)

Реальных ордеров НЕТ — только решение и запись в БД.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# --- Пути проекта и импорт DB utils ---

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(THIS_DIR)              # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)          # .../ai_trading_bot

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.data_collector.db_utils import get_db_connection  # type: ignore

LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "decision_engine.log")

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "btc_snapshot_v2.json")
FLOW_PATH = os.path.join(DATA_DIR, "btc_flow.json")
DECISION_PATH = os.path.join(DATA_DIR, "decision.json")

SYMBOL_DB = "BTCUSDT"

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
        logger.error("decision_engine: file not found: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("decision_engine: failed to load %s: %s", path, e, exc_info=True)
        return None


def save_decision_to_file(decision: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = DECISION_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DECISION_PATH)


# --- Коррекция confidence по ликвидациям ---

def adjust_confidence_with_liq(
    action: str,
    confidence: float,
    liq_metrics: Optional[Dict[str, Any]],
) -> float:
    """
    Простая v1-логика:

    - imbalance_last > 0 и imbalance_delta > 0:
        сверху растёт short-ликвидность → выше риск short-squeeze.
        - если action == 'long'  → чуть повышаем confidence
        - если action == 'short' → чуть понижаем confidence

    - imbalance_last < 0 и imbalance_delta < 0:
        снизу растёт long-ликвидность → выше риск down-sweep.
        - если action == 'short' → чуть повышаем confidence
        - если action == 'long'  → чуть понижаем confidence
    """
    if not liq_metrics or action not in ("long", "short"):
        return confidence

    try:
        imb_last = float(liq_metrics.get("imbalance_last"))
        imb_delta = float(liq_metrics.get("imbalance_delta"))
    except Exception:
        return confidence

    delta = 0.0

    # short-ликвидность сверху растёт
    if imb_last > 0 and imb_delta > 0:
        if action == "long":
            delta += 0.05
        elif action == "short":
            delta -= 0.05

    # long-ликвидность снизу растёт
    if imb_last < 0 and imb_delta < 0:
        if action == "short":
            delta += 0.05
        elif action == "long":
            delta -= 0.05

    new_conf = max(0.0, min(1.0, confidence + delta))
    return new_conf


# --- Основная логика принятия решения v1 ---

def build_decision(snapshot: Dict[str, Any], flow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Базовая логика:
    - risk.mode + crowd.bias → action + базовый confidence
    - потом корректируем confidence с учётом ликвидаций (flow.liq_metrics)
    """
    ts_iso = snapshot.get("timestamp_iso")
    ts_ms = snapshot.get("timestamp_ms")
    price = snapshot.get("price")

    risk = (flow.get("risk") or {})
    risk_mode = risk.get("mode", "neutral")
    risk_score = float(risk.get("global_score", 0.5) or 0.5)

    crowd = (flow.get("crowd") or {})
    crowd_bias = crowd.get("bias", "neutral")
    crowd_score = float(crowd.get("score", 0.5) or 0.5)

    liq_metrics = flow.get("liq_metrics") if isinstance(flow.get("liq_metrics"), dict) else None

    action = "flat"
    confidence = 0.2
    reason = "default_flat"

    # 1) если режим risk_off → сидим ровно
    if risk_mode == "risk_off":
        action = "flat"
        confidence = max(0.1, 0.4 - (risk_score * 0.2))
        reason = "risk_off_mode"
    else:
        # 2) при risk_on смотрим на толпу
        if risk_mode in ("cautious_risk_on", "aggressive_risk_on"):
            if crowd_bias == "bullish":
                action = "long"
                confidence = 0.5 + (crowd_score - 0.5) * 0.5 + (risk_score - 0.5) * 0.3
                reason = "crowd_bullish_risk_on"
            elif crowd_bias == "bearish":
                action = "short"
                confidence = 0.5 + (abs(crowd_score - 0.5)) * 0.5 + (risk_score - 0.5) * 0.3
                reason = "crowd_bearish_risk_on"
            else:
                action = "flat"
                confidence = 0.3 + (risk_score - 0.5) * 0.2
                reason = "risk_on_but_crowd_neutral"
        else:
            # neutral режим
            if crowd_bias == "bullish":
                action = "long"
                confidence = 0.4 + (crowd_score - 0.5) * 0.4
                reason = "crowd_bullish_neutral_risk"
            elif crowd_bias == "bearish":
                action = "short"
                confidence = 0.4 + (abs(crowd_score - 0.5)) * 0.4
                reason = "crowd_bearish_neutral_risk"
            else:
                action = "flat"
                confidence = 0.3
                reason = "neutral_crowd_and_risk"

    # --- корректируем confidence по ликвидациям ---
    confidence_before = confidence
    confidence = adjust_confidence_with_liq(action, confidence, liq_metrics)

    # нормируем
    confidence = max(0.0, min(1.0, confidence))

    decision: Dict[str, Any] = {
        "symbol": SYMBOL_DB,
        "timestamp_iso": ts_iso,
        "timestamp_ms": ts_ms,
        "price": price,

        "action": action,
        "confidence": confidence,
        "reason": reason,

        "context": {
            "risk": risk,
            "crowd": crowd,
            "liq_metrics": liq_metrics,
            "raw": {
                "risk_mode": risk_mode,
                "risk_score": risk_score,
                "crowd_bias": crowd_bias,
                "crowd_score": crowd_score,
                "confidence_before_liq": confidence_before,
            },
        },
    }

    return decision


# --- Запись в таблицу decisions ---

def upsert_decision(conn, decision: Dict[str, Any]) -> None:
    ts_ms = int(decision.get("timestamp_ms") or 0)
    symbol = decision.get("symbol", SYMBOL_DB)
    action = decision.get("action", "flat")
    confidence = float(decision.get("confidence") or 0.0)
    reason = decision.get("reason", "")[:255]

    json_data = json.dumps(decision, ensure_ascii=False)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM decisions WHERE symbol = %s AND timestamp_ms = %s LIMIT 1",
            (symbol, ts_ms),
        )
        row = cur.fetchone()
        if row:
            decision_id = int(row[0])
            sql = """
                UPDATE decisions
                SET action=%s,
                    confidence=%s,
                    reason=%s,
                    json_data=%s
                WHERE id=%s
            """
            cur.execute(sql, (action, confidence, reason, json_data, decision_id))
        else:
            sql = """
                INSERT INTO decisions (
                    timestamp_ms,
                    symbol,
                    action,
                    confidence,
                    reason,
                    json_data
                )
                VALUES (%s,%s,%s,%s,%s,%s)
            """
            cur.execute(
                sql,
                (ts_ms, symbol, action, confidence, reason, json_data),
            )

    conn.commit()


# --- main ---

def main() -> None:
    setup_logging()
    logger.info("decision_engine: started")

    snapshot = load_json(SNAPSHOT_PATH)
    if not snapshot:
        logger.error("decision_engine: snapshot file missing or invalid: %s", SNAPSHOT_PATH)
        sys.exit(1)

    flow = load_json(FLOW_PATH)
    if not flow:
        logger.error("decision_engine: flow file missing or invalid: %s", FLOW_PATH)
        sys.exit(1)

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("decision_engine: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        decision = build_decision(snapshot, flow)
        save_decision_to_file(decision)
        upsert_decision(conn, decision)
        logger.info(
            "decision_engine: decision generated (action=%s, conf=%.3f, ts=%s)",
            decision.get("action"),
            float(decision.get("confidence") or 0.0),
            decision.get("timestamp_iso"),
        )
    except Exception as e:
        logger.error("decision_engine: failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("decision_engine: finished")


if __name__ == "__main__":
    main()
