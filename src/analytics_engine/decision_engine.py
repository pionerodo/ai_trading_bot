"""
Decision Engine v2: deterministic trading decision builder.

- Consumes latest btc_snapshot_v2.json and btc_flow.json.
- Evaluates long/short candidates using structure, momentum and flow context.
- Applies risk checks, ATR-based sizing and produces full decision.json payload.
- Persists the result to JSON and the `decisions` DB table when run as a script.
"""
from __future__ import annotations

import json
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from src.core.config_loader import load_config
from src.data_collector.db_utils import get_db_connection  # type: ignore

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(THIS_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

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
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AccountState:
    equity: float
    trades_today: int = 0
    daily_dd_pct: float = 0.0
    weekly_dd_pct: float = 0.0

    @classmethod
    def from_defaults(cls, config: Dict[str, Any]) -> "AccountState":
        trading = config.get("trading", {})
        return cls(equity=float(trading.get("initial_equity_usd", 10_000.0)))


@dataclass
class CandidateScore:
    direction: str
    structure_score: float
    momentum_score: float
    flow_score: float
    total: float
    reason: str


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------


def _structure_bias(snapshot: Dict[str, Any], direction: str) -> Tuple[float, str]:
    ms = snapshot.get("market_structure") or {}
    weights = {"tf_5m": 0.4, "tf_15m": 0.35, "tf_1h": 0.25}
    score = 0.0
    reasons = []
    for tf, weight in weights.items():
        value = (ms.get(tf) or {}).get("value")
        if direction == "long" and value == "HH-HL":
            score += weight
            reasons.append(f"{tf}_hh_hl")
        if direction == "short" and value == "LL-LH":
            score += weight
            reasons.append(f"{tf}_ll_lh")
        if value == "range":
            score += weight * 0.3
    return _clamp(score, 0.0, 1.0), ";".join(reasons) or "structure_neutral"


def _momentum_bias(snapshot: Dict[str, Any], direction: str) -> Tuple[float, str]:
    mom = snapshot.get("momentum") or {}
    score = 0.0
    reasons = []
    for tf, weight in {"tf_5m": 0.4, "tf_15m": 0.35, "tf_1h": 0.25}.items():
        state = (mom.get(tf) or {}).get("state")
        state_score = float((mom.get(tf) or {}).get("score", 0.5) or 0.5)
        if direction == "long" and state == "impulse_up":
            score += weight * max(0.6, state_score)
            reasons.append(f"{tf}_impulse_up")
        elif direction == "short" and state == "impulse_down":
            score += weight * max(0.6, state_score)
            reasons.append(f"{tf}_impulse_down")
        else:
            score += weight * 0.3
    return _clamp(score), ";".join(reasons) or "momentum_neutral"


def _flow_bias(flow: Dict[str, Any], direction: str) -> Tuple[float, str]:
    reasons = []
    score = 0.4

    crowd = flow.get("crowd") or {}
    if crowd.get("bias") == direction:
        score += 0.25 * float(crowd.get("score", 0.5) or 0.5)
        reasons.append("crowd_alignment")
    elif crowd.get("bias") == "neutral":
        score += 0.05
    else:
        score -= 0.1

    etp = flow.get("etp_summary") or {}
    signal = etp.get("signal")
    if direction == "long" and signal in {"bullish", "heavy_inflow"}:
        score += 0.1
        reasons.append("etf_support")
    elif direction == "short" and signal in {"bearish", "heavy_outflow"}:
        score += 0.1
        reasons.append("etf_headwind_to_bulls")

    liq = flow.get("liq_summary") or {}
    dominant = (liq.get("dominant_side") or "").lower()
    if direction == "long" and dominant == "bears":
        score += 0.05
        reasons.append("liq_above_price")
    elif direction == "short" and dominant == "bulls":
        score += 0.05
        reasons.append("liq_below_price")

    trap_index = float(flow.get("crowd_trap_index", 0.0) or 0.0)
    if direction == "long" and trap_index < 0:
        score -= abs(trap_index)
        reasons.append("trap_risk_long")
    if direction == "short" and trap_index > 0:
        score -= abs(trap_index)
        reasons.append("trap_risk_short")

    news = flow.get("news_sentiment") or {}
    news_score = float(news.get("score", 0.0) or 0.0)
    if direction == "long" and news_score > 0.2:
        score += 0.05
        reasons.append("news_bullish")
    elif direction == "short" and news_score < -0.2:
        score += 0.05
        reasons.append("news_bearish")

    return _clamp(score), ";".join(reasons) or "flow_neutral"


def _score_candidate(snapshot: Dict[str, Any], flow: Dict[str, Any], direction: str) -> CandidateScore:
    structure_score, s_reason = _structure_bias(snapshot, direction)
    momentum_score, m_reason = _momentum_bias(snapshot, direction)
    flow_score, f_reason = _flow_bias(flow, direction)

    total = _clamp(0.4 * structure_score + 0.35 * momentum_score + 0.25 * flow_score)
    reason = ",".join([s_reason, m_reason, f_reason])
    return CandidateScore(direction, structure_score, momentum_score, flow_score, total, reason)


# ---------------------------------------------------------------------------
# Risk checks & sizing
# ---------------------------------------------------------------------------


def _build_risk_checks(flow: Dict[str, Any], account: AccountState) -> Dict[str, bool]:
    cfg = load_config()
    risk_cfg = cfg.get("risk", {})
    risk_mode = (flow.get("risk") or {}).get("mode", "neutral")
    warnings = flow.get("warnings") or []

    max_daily_dd = float(risk_cfg.get("max_daily_dd_pct", -2.0))
    max_weekly_dd = float(risk_cfg.get("max_weekly_dd_pct", -5.0))
    max_trades_per_day = int(risk_cfg.get("max_trades_per_day", 3))

    checks = {
        "daily_dd_ok": account.daily_dd_pct >= max_daily_dd,
        "weekly_dd_ok": account.weekly_dd_pct >= max_weekly_dd,
        "max_trades_per_day_ok": account.trades_today < max_trades_per_day,
        "session_ok": True,
        "no_major_news": "major_news" not in warnings,
    }

    session_block = flow.get("session") or {}
    if isinstance(session_block, dict) and session_block.get("restricted"):
        checks["session_ok"] = False

    if risk_mode == "risk_off":
        checks = {k: False if k != "session_ok" else checks[k] for k in checks}
    if "volatility_high" in warnings:
        checks["session_ok"] = False

    return checks


def _atr_stop(snapshot: Dict[str, Any]) -> Optional[float]:
    atr_block = ((snapshot.get("volatility") or {}).get("atr") or {})
    for tf in ("tf_15m", "tf_5m", "tf_1h"):
        if tf in atr_block and atr_block[tf].get("atr"):
            return float(atr_block[tf]["atr"])
    return None


def _sizing(
    price: float,
    atr: Optional[float],
    account: AccountState,
    cfg: Dict[str, Any],
    risk_mode: str,
) -> Tuple[float, float, float]:
    risk_cfg = cfg.get("risk", {})
    trading_cfg = cfg.get("trading", {})

    risk_pct = float(risk_cfg.get("risk_pct_per_trade", trading_cfg.get("max_risk_pct_per_trade", 0.01)))
    stop_distance = atr if atr else price * 0.005
    if stop_distance <= 0:
        stop_distance = price * 0.005

    position_risk_usd = account.equity * risk_pct
    notional = position_risk_usd / (stop_distance / price)
    position_size_usdt = float(min(notional, float(trading_cfg.get("position_size_cap_usd", notional))))

    leverage_caps = cfg.get("binance", {}).get("leverage_caps", {})
    leverage_default = float(cfg.get("binance", {}).get("max_leverage", 3))
    leverage_cap = float(leverage_caps.get(risk_mode, leverage_default))
    leverage = min(max(1.0, position_size_usdt / account.equity), leverage_cap)

    return position_size_usdt, leverage, stop_distance


# ---------------------------------------------------------------------------
# Decision builder
# ---------------------------------------------------------------------------


def compute_decision(
    snapshot: Dict[str, Any],
    flow: Dict[str, Any],
    account_state: Optional[AccountState] = None,
) -> Dict[str, Any]:
    config = load_config()
    account = account_state or AccountState.from_defaults(config)
    price = float(snapshot.get("price") or 0.0)
    timestamp_iso = snapshot.get("timestamp_iso") or datetime.now(timezone.utc).isoformat()
    timestamp_dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))

    long_cand = _score_candidate(snapshot, flow, "long")
    short_cand = _score_candidate(snapshot, flow, "short")

    best = max((long_cand, short_cand), key=lambda c: c.total)
    second = min((long_cand, short_cand), key=lambda c: c.total)

    risk_checks = _build_risk_checks(flow, account)
    all_checks_ok = all(risk_checks.values())

    # Resolve conflicts
    action = "flat"
    reason = "conflict_or_low_score"
    confidence = 0.25
    if best.total - second.total > 0.08 and best.total > 0.45:
        action = best.direction
        reason = best.reason
        confidence = _clamp(best.total + float(flow.get("alignment_score", 0.5) or 0.5) * 0.2)
    elif best.total < 0.35:
        action = "flat"
        reason = "signals_weak"
        confidence = best.total

    if not all_checks_ok:
        action = "flat"
        confidence = min(confidence, 0.49)
        reason = "risk_checks_blocked"

    atr = _atr_stop(snapshot)
    risk_mode = (flow.get("risk") or {}).get("mode", "neutral")
    position_size_usdt, leverage, stop_distance = _sizing(price, atr, account, config, risk_mode)
    zone_half = stop_distance * 0.4

    if action == "long":
        entry_zone = [price - zone_half, price + zone_half]
        sl = price - stop_distance
        tp1 = price + stop_distance * 1.5
        tp2 = price + stop_distance * 2.5
    elif action == "short":
        entry_zone = [price - zone_half, price + zone_half]
        sl = price + stop_distance
        tp1 = price - stop_distance * 1.5
        tp2 = price - stop_distance * 2.5
    else:
        entry_zone = []
        sl = None
        tp1 = None
        tp2 = None
        position_size_usdt = 0.0
        leverage = 0.0

    decision = {
        "symbol": snapshot.get("symbol", "BTCUSDT"),
        "timestamp_iso": timestamp_iso,
        "timestamp": timestamp_dt.isoformat(),
        "price": price,
        "action": action,
        "reason": reason,
        "entry_zone": entry_zone,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_level": 3 if action != "flat" else 0,
        "position_size_usdt": round(position_size_usdt, 2),
        "leverage": round(leverage, 2),
        "confidence": round(confidence, 3),
        "risk_checks": risk_checks,
        "risk": flow.get("risk", {}),
        "context": {
            "structure": {
                "long": long_cand.structure_score,
                "short": short_cand.structure_score,
            },
            "momentum": {
                "long": long_cand.momentum_score,
                "short": short_cand.momentum_score,
            },
            "flow": {
                "long": long_cand.flow_score,
                "short": short_cand.flow_score,
            },
            "warnings": flow.get("warnings", []),
        },
    }

    return decision


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def upsert_decision(conn, decision: Dict[str, Any]) -> None:
    symbol = decision.get("symbol", "BTCUSDT")
    action = decision.get("action", "flat")
    confidence = float(decision.get("confidence") or 0.0)
    reason = decision.get("reason", "")[:255]
    timestamp_iso = decision.get("timestamp_iso") or decision.get("timestamp")
    timestamp_dt = datetime.fromisoformat(str(timestamp_iso).replace("Z", "+00:00"))
    entry_zone = decision.get("entry_zone") or []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM decisions WHERE symbol = %s AND timestamp = %s LIMIT 1",
            (symbol, timestamp_dt),
        )
        row = cur.fetchone()
        params = (
            symbol,
            timestamp_dt,
            action,
            reason,
            entry_zone[0] if entry_zone else None,
            entry_zone[1] if len(entry_zone) > 1 else None,
            decision.get("sl"),
            decision.get("tp1"),
            decision.get("tp2"),
            int(decision.get("risk_level", 0) or 0),
            float(decision.get("position_size_usdt", 0.0) or 0.0),
            float(decision.get("leverage", 0.0) or 0.0),
            confidence,
            json.dumps(decision.get("risk_checks", {}), ensure_ascii=False),
        )

        if row:
            decision_id = int(row[0])
            sql = """
                UPDATE decisions
                SET symbol=%s,
                    timestamp=%s,
                    action=%s,
                    reason=%s,
                    entry_min_price=%s,
                    entry_max_price=%s,
                    sl_price=%s,
                    tp1_price=%s,
                    tp2_price=%s,
                    risk_level=%s,
                    position_size_usdt=%s,
                    leverage=%s,
                    confidence=%s,
                    risk_checks_json=%s
                WHERE id=%s
            """
            cur.execute(sql, (*params, decision_id))
        else:
            sql = """
                INSERT INTO decisions (
                    symbol,
                    timestamp,
                    action,
                    reason,
                    entry_min_price,
                    entry_max_price,
                    sl_price,
                    tp1_price,
                    tp2_price,
                    risk_level,
                    position_size_usdt,
                    leverage,
                    confidence,
                    risk_checks_json
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
            """
            cur.execute(sql, params)

    conn.commit()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()
    logger.info("decision_engine: started")

    snapshot = _safe_load_json(SNAPSHOT_PATH)
    flow = _safe_load_json(FLOW_PATH)
    if not snapshot or not flow:
        logger.error("decision_engine: missing snapshot or flow")
        sys.exit(1)

    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error("decision_engine: cannot get DB connection: %s", e, exc_info=True)
        sys.exit(1)

    try:
        decision = compute_decision(snapshot, flow)
        _save_json(DECISION_PATH, decision)
        upsert_decision(conn, decision)
        logger.info(
            "decision_engine: decision %s (conf=%.2f, size=%.0f) at %s",
            decision.get("action"),
            float(decision.get("confidence", 0.0)),
            float(decision.get("position_size_usdt", 0.0)),
            decision.get("timestamp_iso"),
        )
    except Exception as e:  # pragma: no cover - runtime safeguard
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
