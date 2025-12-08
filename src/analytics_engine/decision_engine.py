"""
Decision Engine v2: deterministic trading decision builder.

- Consumes latest btc_snapshot.json and btc_flow.json.
- Evaluates long/short candidates using structure, momentum and flow context.
- Applies risk checks, ATR-based sizing and produces full decision.json payload.
- Persists the result to JSON and the `decisions` DB table when run as a script.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# --- Ensure project root on sys.path for cron execution ---
CURRENT_FILE = os.path.abspath(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_FILE)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.config_loader import load_config
from src.data_collector.db_utils import get_db_connection

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "btc_snapshot.json")
FLOW_PATH = os.path.join(DATA_DIR, "btc_flow.json")
DECISION_PATH = os.path.join(DATA_DIR, "decision.json")
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "decision_engine.log")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def _safe_load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        logger.error("decision_engine: file not found: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # pragma: no cover - defensive logging
        logger.error("decision_engine: failed to load %s: %s", path, e, exc_info=True)
        return None


def _save_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
    except Exception:  # pragma: no cover - fallback for local runs
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


# ---------------------------------------------------------------------------
# Risk policy settings
# ---------------------------------------------------------------------------


dataclass_json = Tuple[float, float, float, float]


@dataclass
class RiskPolicy:
    max_daily_dd: float = 0.05
    max_weekly_dd: float = 0.12
    max_trades_per_day: int = 10
    min_confidence: float = 0.55
    etp_warning_block: bool = True
    liquidation_warning_block: bool = True
    news_warning_block: bool = False


RISK_POLICY = RiskPolicy()


# ---------------------------------------------------------------------------
# Decision logic helpers
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    action: str
    confidence: float
    rationale: str
    price_ref: float
    stop_loss: float
    take_profit: float
    position_size: float
    snapshot_id: Optional[int]
    flow_id: Optional[int]
    risk_flags: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "price_ref": self.price_ref,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size": self.position_size,
            "snapshot_id": self.snapshot_id,
            "flow_id": self.flow_id,
            "risk_flags": self.risk_flags,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _extract_price(snapshot: Dict[str, Any]) -> Optional[float]:
    try:
        return float(snapshot.get("price"))
    except Exception:
        return None


def _extract_atr(snapshot: Dict[str, Any]) -> Optional[float]:
    structure = snapshot.get("structure", {}) if isinstance(snapshot, dict) else {}
    try:
        return float(structure.get("atr"))
    except Exception:
        return None


def _extract_momentum(snapshot: Dict[str, Any]) -> Optional[float]:
    try:
        return float(snapshot.get("momentum", {}).get("score"))
    except Exception:
        return None


def _extract_flow_score(flow: Dict[str, Any]) -> Optional[float]:
    try:
        return float(flow.get("flow_score"))
    except Exception:
        return None


def _risk_blockers(flow: Dict[str, Any]) -> Dict[str, bool]:
    flags = {
        "etf_warning": False,
        "liquidation_warning": False,
        "news_warning": False,
    }
    warnings = flow.get("warnings", {}) if isinstance(flow, dict) else {}
    if warnings.get("etf_warning"):
        flags["etf_warning"] = True
    if warnings.get("liquidation_warning"):
        flags["liquidation_warning"] = True
    news = flow.get("news", {}) if isinstance(flow, dict) else {}
    try:
        if news.get("sentiment") == "bearish" and abs(float(news.get("score", 0.0))) > 0.5:
            flags["news_warning"] = True
    except Exception:
        pass
    return flags


def _evaluate_direction(momentum: Optional[float], flow_score: Optional[float]) -> Tuple[str, float, str]:
    if momentum is None or flow_score is None:
        return "hold", 0.0, "insufficient data"

    avg_score = (momentum + flow_score) / 2.0
    if avg_score > 0.6:
        return "long", avg_score, "momentum+flow bullish"
    if avg_score < -0.6:
        return "short", abs(avg_score), "momentum+flow bearish"
    return "hold", abs(avg_score), "neutral band"


def _apply_risk_checks(direction: str, confidence: float, price: float, atr: float, flow_flags: Dict[str, bool]) -> Tuple[str, float, Dict[str, bool]]:
    flags = flow_flags.copy()

    if confidence < RISK_POLICY.min_confidence:
        flags["low_confidence"] = True
        return "hold", confidence, flags

    if direction == "hold":
        flags["neutral"] = True
        return direction, confidence, flags

    if flow_flags.get("etf_warning") and RISK_POLICY.etp_warning_block:
        flags["blocked_etf"] = True
        return "hold", confidence, flags

    if flow_flags.get("liquidation_warning") and RISK_POLICY.liquidation_warning_block:
        flags["blocked_liquidation"] = True
        return "hold", confidence, flags

    if flow_flags.get("news_warning") and RISK_POLICY.news_warning_block:
        flags["blocked_news"] = True
        return "hold", confidence, flags

    if atr and atr > 0 and price:
        sl = price - 1.5 * atr if direction == "long" else price + 1.5 * atr
        tp = price + 3 * atr if direction == "long" else price - 3 * atr
    else:
        sl = price * 0.99 if direction == "long" else price * 1.01
        tp = price * 1.02 if direction == "long" else price * 0.98

    position_size = _clamp(confidence, 0.1, 1.0)
    return direction, confidence, {
        **flags,
        "stop_loss": sl,
        "take_profit": tp,
        "position_size": position_size,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _lookup_snapshot_flow_ids(conn, snapshot_timestamp: datetime, flow_timestamp: datetime) -> Tuple[Optional[int], Optional[int]]:
    snapshot_id = None
    flow_id = None

    if isinstance(snapshot_timestamp, str):
        snapshot_timestamp = datetime.fromisoformat(snapshot_timestamp)

    if isinstance(flow_timestamp, str):
        flow_timestamp = datetime.fromisoformat(flow_timestamp)

    sql_snapshot = "SELECT id FROM snapshots WHERE symbol=%s AND created_at=%s LIMIT 1"
    sql_flow = "SELECT id FROM flows WHERE symbol=%s AND created_at=%s LIMIT 1"

    with conn.cursor() as cur:
        cur.execute(sql_snapshot, ("BTCUSDT", snapshot_timestamp))
        row = cur.fetchone()
        if row:
            snapshot_id = row[0]

        cur.execute(sql_flow, ("BTCUSDT", flow_timestamp))
        row = cur.fetchone()
        if row:
            flow_id = row[0]

    return snapshot_id, flow_id


def _insert_decision(conn, decision: Decision, snapshot_ts: datetime) -> None:
    columns = [
        "symbol",
        "timestamp",
        "created_at",
        "action",
        "confidence",
        "reason",
        "entry_min_price",
        "entry_max_price",
        "sl_price",
        "tp1_price",
        "tp2_price",
        "position_size_usdt",
        "leverage",
        "risk_level",
        "risk_checks_json",
        "snapshot_id",
        "flow_id",
    ]

    values = (
        "BTCUSDT",
        snapshot_ts,
        datetime.now(timezone.utc),
        decision.action,
        decision.confidence,
        decision.rationale,
        decision.price_ref,
        decision.price_ref,
        decision.stop_loss,
        decision.take_profit,
        None,
        decision.position_size,
        0.0,
        0,
        json.dumps(decision.risk_flags, ensure_ascii=False),
        decision.snapshot_id,
        decision.flow_id,
    )

    is_sqlite = conn.__class__.__module__.startswith("sqlite3")
    placeholder = ",".join(["?"] * len(columns)) if is_sqlite else ",".join(["%s"] * len(columns))

    if is_sqlite:
        sql = f"""
            INSERT INTO decisions ({','.join(columns)})
            VALUES ({placeholder})
            ON CONFLICT(symbol, timestamp) DO UPDATE SET
                action=excluded.action,
                confidence=excluded.confidence,
                reason=excluded.reason,
                entry_min_price=excluded.entry_min_price,
                entry_max_price=excluded.entry_max_price,
                sl_price=excluded.sl_price,
                tp1_price=excluded.tp1_price,
                tp2_price=excluded.tp2_price,
                position_size_usdt=excluded.position_size_usdt,
                leverage=excluded.leverage,
                risk_level=excluded.risk_level,
                risk_checks_json=excluded.risk_checks_json,
                snapshot_id=excluded.snapshot_id,
                flow_id=excluded.flow_id
        """
    else:
        sql = f"""
            INSERT INTO decisions ({','.join(columns)})
            VALUES ({placeholder})
            ON DUPLICATE KEY UPDATE
                action=VALUES(action),
                confidence=VALUES(confidence),
                reason=VALUES(reason),
                entry_min_price=VALUES(entry_min_price),
                entry_max_price=VALUES(entry_max_price),
                sl_price=VALUES(sl_price),
                tp1_price=VALUES(tp1_price),
                tp2_price=VALUES(tp2_price),
                position_size_usdt=VALUES(position_size_usdt),
                leverage=VALUES(leverage),
                risk_level=VALUES(risk_level),
                risk_checks_json=VALUES(risk_checks_json),
                snapshot_id=VALUES(snapshot_id),
                flow_id=VALUES(flow_id)
        """

    cur = conn.cursor()
    try:
        cur.execute(sql, values)
    finally:
        try:
            cur.close()
        except Exception:
            pass
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_decision(snapshot: Dict[str, Any], flow: Dict[str, Any]) -> Decision:
    price = _extract_price(snapshot)
    atr = _extract_atr(snapshot) or 0.0
    momentum_score = _extract_momentum(snapshot)
    flow_score = _extract_flow_score(flow)

    direction, confidence, rationale = _evaluate_direction(momentum_score, flow_score)
    flow_flags = _risk_blockers(flow)

    if price is None:
        return Decision(
            action="hold",
            confidence=0.0,
            rationale="missing price",
            price_ref=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            position_size=0.0,
            snapshot_id=None,
            flow_id=None,
            risk_flags={"invalid_input": True},
        )

    direction, confidence, risk_flags = _apply_risk_checks(direction, confidence, price, atr, flow_flags)

    stop_loss = risk_flags.pop("stop_loss", price)
    take_profit = risk_flags.pop("take_profit", price)
    position_size = risk_flags.pop("position_size", 0.0)

    return Decision(
        action=direction,
        confidence=confidence,
        rationale=rationale,
        price_ref=price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size=position_size,
        snapshot_id=None,
        flow_id=None,
        risk_flags=risk_flags,
    )


def main() -> None:
    setup_logging()
    logger.info("decision_engine: started")

    cfg = load_config()
    decision_enabled = cfg.get("decision_engine", {}).get("enabled", True)
    if not decision_enabled:
        logger.info("decision_engine: disabled via config")
        return

    snapshot = _safe_load_json(SNAPSHOT_PATH)
    flow = _safe_load_json(FLOW_PATH)

    if not snapshot or not flow:
        logger.error("decision_engine: missing snapshot or flow; aborting run")
        return

    snapshot_ts = snapshot.get("captured_at_utc") or snapshot.get("timestamp")
    flow_ts = flow.get("captured_at_utc") or flow.get("timestamp")
    if not snapshot_ts or not flow_ts:
        logger.error("decision_engine: missing timestamps; aborting run")
        return

    try:
        snapshot_dt = datetime.fromisoformat(snapshot_ts)
        flow_dt = datetime.fromisoformat(flow_ts)
    except Exception as e:  # pragma: no cover - defensive logging
        logger.error("decision_engine: invalid timestamp format: %s", e, exc_info=True)
        return

    decision = _build_decision(snapshot, flow)

    decision.snapshot_id = snapshot.get("db_id")
    decision.flow_id = flow.get("db_id")

    payload = decision.to_dict()
    payload.update({
        "symbol": "BTCUSDT",
        "timestamp": snapshot_ts,
        "flow_timestamp": flow_ts,
        "timestamp_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
    })

    _save_json(DECISION_PATH, payload)

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("decision_engine: DB connection error: %s", e, exc_info=True)
        return

    try:
        snap_id, flow_id = _lookup_snapshot_flow_ids(conn, snapshot_dt, flow_dt)
        decision.snapshot_id = snap_id
        decision.flow_id = flow_id

        _insert_decision(conn, decision, snapshot_dt)
        logger.info(
            "decision_engine: saved decision action=%s confidence=%.3f snapshot_id=%s flow_id=%s",
            decision.action,
            decision.confidence,
            decision.snapshot_id,
            decision.flow_id,
        )
    except Exception as e:  # pragma: no cover - defensive logging
        logger.error("decision_engine: failed to insert decision: %s", e, exc_info=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
