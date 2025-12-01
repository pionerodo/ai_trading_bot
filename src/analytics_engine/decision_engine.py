import logging
from typing import Any, Dict


logger = logging.getLogger("ai_trading_bot")


def _safe_get(d: Dict[str, Any], path: str, default=None):
    """
    Utility to safely read nested keys from dict using "a.b.c" path.
    """
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def compute_decision(snapshot: Dict[str, Any], flow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based decision engine with explicit risk/meta block.

    Uses only data already prepared in `flow` / `snapshot`:

    - flow.trend_score     : aggregated multi-TF trend score (negative = bearish)
    - flow.alignment_score : how well TFs agree [0..1]
    - flow.volatility_*    : regime + score
    - flow.crowd_trend     : "bullish" / "bearish" / "neutral"
    - flow.etp_summary     : BTC ETF flows impact
    - flow.liq_summary     : liquidation map impact

    Output:
      {
        action: "LONG"/"SHORT"/"FLAT",
        confidence: 0..1,
        reason: "...",
        risk: { level, mode, global_score, checks{...} },
        meta: {...}
      }
    """

    # ---- 1. Base fields from flow ----
    trend_score = float(flow.get("trend_score", 0.0))
    alignment_score = float(flow.get("alignment_score", 0.0))
    volatility_regime = flow.get("volatility_regime", "unknown")
    volatility_score = float(flow.get("volatility_score", 0.0))
    crowd_trend = flow.get("crowd_trend", "neutral")

    # ETF block (optional)
    etp_summary = flow.get("etp_summary") or {}
    etp_net_flow_usd = float(etp_summary.get("net_flow_usd", 0.0))
    etp_net_flow_3d_usd = float(etp_summary.get("net_flow_3d_usd", 0.0))
    etp_signal = etp_summary.get("signal", "none")

    # Liquidations map block (optional)
    liq_summary = flow.get("liq_summary") or {}
    liq_dominant_side = liq_summary.get("dominant_side", "none")  # "shorts"/"longs"/"none"
    liq_price = liq_summary.get("current_price")
    liq_upside_zone = liq_summary.get("upside_focus_zone")
    liq_downside_zone = liq_summary.get("downside_focus_zone")

    # Crowd trap index / news sentiment (optional, may be absent)
    crowd_trap_index = float(flow.get("crowd_trap_index", 0.0))
    news_sentiment_score = float(flow.get("news_sentiment_score", 0.0))

    # ---- 2. Determine base directional bias ----
    # Thresholds for trend strength
    strong_trend = 2.5
    weak_trend = 1.0

    if trend_score > strong_trend:
        base_action = "LONG"
    elif trend_score < -strong_trend:
        base_action = "SHORT"
    elif abs(trend_score) <= weak_trend:
        base_action = "FLAT"
    else:
        # Moderate trend – follow direction but with lower confidence
        base_action = "LONG" if trend_score > 0 else "SHORT"

    # ---- 3. Adjust by alignment / volatility / ETF / liquidations ----
    confidence = 0.5  # start from neutral

    # Trend strength contribution
    confidence += min(abs(trend_score) / 5.0, 0.3)  # up to +0.3

    # Alignment contribution (0..1)
    confidence += (alignment_score - 0.5) * 0.4  # from -0.2..+0.2 roughly

    # Volatility regime: too high volatility reduces confidence
    if volatility_regime in ("extreme", "very_high"):
        confidence -= 0.25
    elif volatility_regime == "high":
        confidence -= 0.1
    elif volatility_regime == "low":
        confidence -= 0.05

    # ETF flows: strong 3d net inflow/outflow add directional conviction
    etp_boost = 0.0
    if abs(etp_net_flow_3d_usd) > 300_000_000:  # 300M+
        etp_boost = 0.15
    elif abs(etp_net_flow_3d_usd) > 100_000_000:
        etp_boost = 0.07

    if etp_net_flow_3d_usd > 0 and base_action == "LONG":
        confidence += etp_boost
    elif etp_net_flow_3d_usd < 0 and base_action == "SHORT":
        confidence += etp_boost
    elif etp_net_flow_3d_usd * trend_score < 0:
        # ETF против тренда – слегка душим уверенность
        confidence -= etp_boost

    # Liquidations: prefer moving toward dense opposite-side clusters
    if liq_dominant_side == "shorts" and base_action == "LONG":
        confidence += 0.1
    elif liq_dominant_side == "longs" and base_action == "SHORT":
        confidence += 0.1

    # Crowd trap index: if extreme – cut confidence
    if abs(crowd_trap_index) >= 2.0:
        confidence -= 0.1

    # Clamp to [0,1]
    confidence = max(0.0, min(1.0, confidence))

    # If base_action is FLAT – force low confidence
    if base_action == "FLAT":
        confidence = min(confidence, 0.3)

    action = base_action

    # ---- 4. Risk classification (analytics only, executor already has hard guardrails) ----
    checks: Dict[str, bool] = {}

    # Trend strong enough?
    checks["trend_strength_ok"] = abs(trend_score) >= weak_trend

    # Timeframe alignment OK?
    checks["alignment_ok"] = alignment_score >= 0.55

    # Volatility acceptable?
    checks["volatility_ok"] = volatility_regime not in ("extreme", "very_high")

    # ETF not screaming against the trade?
    if base_action == "LONG":
        checks["etp_ok"] = etp_net_flow_3d_usd >= -150_000_000
    elif base_action == "SHORT":
        checks["etp_ok"] = etp_net_flow_3d_usd <= 150_000_000
    else:
        checks["etp_ok"] = True

    # Liquidations: avoid trading *into* dominant side with very low confidence
    if liq_dominant_side == "shorts" and base_action == "SHORT":
        checks["liq_ok"] = confidence >= 0.5
    elif liq_dominant_side == "longs" and base_action == "LONG":
        checks["liq_ok"] = confidence >= 0.5
    else:
        checks["liq_ok"] = True

    # Global OK flag (used mostly for diagnostics; executor has its own PnL-based guard)
    checks["global_risk_ok"] = all(checks.values())

    # Risk mode / level
    if not checks["global_risk_ok"]:
        risk_mode = "cautious"
        risk_level = 0
    else:
        if abs(trend_score) >= strong_trend and alignment_score >= 0.7 and volatility_regime in ("normal", "high"):
            risk_mode = "trend_following"
            risk_level = 2
        elif abs(trend_score) <= weak_trend:
            risk_mode = "sideways"
            risk_level = 1
        else:
            risk_mode = "mixed"
            risk_level = 1

    # Simple global_score 0..1 just for monitoring
    # (does NOT directly control execution; we keep executor logic explicit)
    components = [
        min(abs(trend_score) / 5.0, 1.0),
        max(min(alignment_score, 1.0), 0.0),
        max(0.0, 1.0 - abs(volatility_score)),  # penalty for wild volatility
    ]
    global_score = sum(components) / len(components)

    # ---- 5. Human-readable reason ----
    reason_parts = [risk_mode, f"trend_score={trend_score:.2f}", f"align={alignment_score:.2f}"]

    if etp_net_flow_usd != 0:
        reason_parts.append(f"etp_1d={'in' if etp_net_flow_usd > 0 else 'out'} {abs(etp_net_flow_usd) / 1_000_000:.1f}M")
    if etp_net_flow_3d_usd != 0:
        reason_parts.append(f"etp_3d={'in' if etp_net_flow_3d_usd > 0 else 'out'} {abs(etp_net_flow_3d_usd) / 1_000_000:.1f}M")
    if liq_dominant_side != "none":
        reason_parts.append(f"liq: {liq_dominant_side}")

    reason = "|".join(reason_parts)

    # ---- 6. Build result ----
    meta = {
        "trend_score_from_flow": trend_score,
        "alignment_score": alignment_score,
        "volatility_regime": volatility_regime,
        "volatility_score": volatility_score,
        "crowd_trend": crowd_trend,
        "crowd_trap_index": crowd_trap_index,
        "etp_net_flow_usd": etp_net_flow_usd,
        "etp_net_flow_3d_usd": etp_net_flow_3d_usd,
        "etp_signal": etp_signal,
        "liq_dominant_side": liq_dominant_side,
        "liq_price": liq_price,
        "liq_upside_zone": liq_upside_zone,
        "liq_downside_zone": liq_downside_zone,
        "news_sentiment_score": news_sentiment_score,
    }

    return {
        "action": action,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "risk": {
            "level": risk_level,
            "mode": risk_mode,
            "global_score": round(global_score, 3),
            "checks": checks,
        },
        "meta": meta,
    }
