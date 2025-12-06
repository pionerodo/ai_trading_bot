import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List

from src.core.config_loader import get_base_dir

logger = logging.getLogger("ai_trading_bot")


def _safe_load_json(path: Path, default: Any) -> Any:
    """
    Безопасная загрузка JSON.
    Если файл не найден или битый — возвращаем default.
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load JSON %s: %s", path, e)
        return default


def _sign_from_value(value: float) -> str:
    if value > 0:
        return "inflow"
    if value < 0:
        return "outflow"
    return "flat"


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def _load_news_sentiment(base_dir: Path) -> Optional[Dict[str, Any]]:
    sentiment_path = base_dir / "data" / "news_sentiment.json"
    data = _safe_load_json(sentiment_path, {})
    if not isinstance(data, dict) or "score" not in data:
        return None
    try:
        return {
            "score": float(data.get("score", 0.0)),
            "comment": data.get("comment") or data.get("summary"),
            "captured_at": data.get("captured_at"),
        }
    except Exception:
        return None


def _build_basic_flow_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Фолбэк, если btc_flow.json ещё нет.
    Достаём базовые вещи из snapshot: market_structure, momentum, session.
    Это лучше, чем совсем пустой flow.
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    timestamp_iso = snapshot.get("timestamp_iso")

    session = snapshot.get("session") or {}
    volatility_regime = session.get("volatility_regime", "unknown")

    # Простейшее определение crowd_trend по market_structure 5m
    ms_5m = ((snapshot.get("market_structure") or {}).get("tf_5m") or "").upper()
    if "HH" in ms_5m and "HL" in ms_5m:
        crowd_trend = "bullish"
    elif "LL" in ms_5m and "LH" in ms_5m:
        crowd_trend = "bearish"
    else:
        crowd_trend = "neutral"

    # Оценка тренда по momentum 5m (score 0–1 → -2..+2)
    m_5m = ((snapshot.get("momentum") or {}).get("tf_5m") or {}).get("score")
    if isinstance(m_5m, (int, float)):
        trend_score = max(-2.0, min(2.0, (float(m_5m) - 0.5) * 4.0))
        vol_score = abs((float(m_5m) - 0.5) * 2.0)  # грубая оценка "насколько всё рвёт"
    else:
        trend_score = 0.0
        vol_score = 1.0

    flow: Dict[str, Any] = {
        "symbol": symbol,
        "timestamp_iso": timestamp_iso,
        "crowd_trend": crowd_trend,
        "trend_score": round(trend_score, 3),
        "alignment_score": 0.5,  # нейтральный базовый alignment
        "volatility_score": round(vol_score, 3),
        "volatility_regime": volatility_regime,
        "crowd_trap_index": 0.0,
        "risk": {
            "global_score": 0.4,
            "mode": "balanced",
        },
        "news_sentiment": {
            "score": 0.0,
        },
        "reasons": ["basic_flow_from_snapshot"],
    }
    return flow


def _compute_crowd_bias(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    ms = snapshot.get("market_structure") or {}
    mom = snapshot.get("momentum") or {}

    bullish_votes = 0
    bearish_votes = 0

    for tf in ("tf_5m", "tf_15m", "tf_1h"):
        structure = (ms.get(tf) or {}).get("value")
        if structure == "HH-HL":
            bullish_votes += 1
        elif structure == "LL-LH":
            bearish_votes += 1

        momentum_state = (mom.get(tf) or {}).get("state")
        if momentum_state == "impulse_up":
            bullish_votes += 1
        elif momentum_state == "impulse_down":
            bearish_votes += 1

    if bullish_votes > bearish_votes:
        bias = "bullish"
    elif bearish_votes > bullish_votes:
        bias = "bearish"
    else:
        bias = "neutral"

    total_votes = bullish_votes + bearish_votes or 1
    score = max(bullish_votes, bearish_votes) / total_votes

    return {
        "bias": bias,
        "score": round(score, 3),
        "trend": (ms.get("tf_5m") or {}).get("value", "unclear"),
    }


def _compute_trap_index(crowd_bias: str, liq_summary: Optional[Dict[str, Any]]) -> float:
    if not liq_summary:
        return 0.0

    dominant = (liq_summary.get("dominant_side") or "").lower()
    if dominant == "bulls":
        liq_bias = "bullish"
    elif dominant == "bears":
        liq_bias = "bearish"
    else:
        liq_bias = "neutral"

    if crowd_bias == "bullish" and liq_bias == "bullish":
        return -0.15  # риск лонг-трапа
    if crowd_bias == "bearish" and liq_bias == "bearish":
        return 0.15   # риск шорт-трапа
    return 0.0


def _compute_risk_block(snapshot: Dict[str, Any], flow: Dict[str, Any]) -> Dict[str, Any]:
    session = (snapshot.get("session") or {})
    vol_regime = (session.get("volatility_regime") or "unknown").lower()
    crowd = (flow.get("crowd") or {})
    warnings = flow.get("warnings") or []

    base_score = 0.5
    if crowd.get("bias") == "bullish" or crowd.get("bias") == "bearish":
        base_score += 0.05
    if vol_regime == "low":
        base_score -= 0.05
    elif vol_regime == "high":
        base_score -= 0.15

    if warnings:
        base_score -= 0.1

    base_score = max(0.0, min(1.0, base_score))

    if base_score < 0.25:
        mode = "risk_off"
    elif base_score < 0.45:
        mode = "neutral"
    elif base_score < 0.7:
        mode = "cautious_risk_on"
    else:
        mode = "aggressive_risk_on"

    return {"global_score": round(base_score, 3), "mode": mode}


def _build_warnings(flow: Dict[str, Any], snapshot: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []

    session = snapshot.get("session") or {}
    if (session.get("volatility_regime") or "").lower() == "high":
        warnings.append("volatility_high")

    etp_summary = flow.get("etp_summary") or {}
    if (etp_summary.get("signal") or "") in {"heavy_outflow", "bearish"}:
        warnings.append("etf_outflow_headwind")

    liq_summary = flow.get("liq_summary") or {}
    if (liq_summary.get("dominant_side") or "").lower() == "bears":
        warnings.append("liq_cluster_above_price")

    return warnings


def _build_etp_summary(base_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Собираем etp_summary из data/btc_etp_flow.json

    Ожидаемый формат btc_etp_flow.json:
    {
      "symbol": "BTC",
      "source": "...",
      "days": [
        {
          "date_display": "...",
          "date_iso": "YYYY-MM-DD",
          "timestamp_ms": 1762819200000,
          "total_flow_usd": 524000000,
          ...
        },
        ...
      ],
      "notes": ""
    }
    """
    etp_path = base_dir / "data" / "btc_etp_flow.json"
    data = _safe_load_json(etp_path, {})
    days: List[Dict[str, Any]] = data.get("days") or []
    if not days:
        return None

    # Сортируем по timestamp_ms
    days_sorted = sorted(
        days,
        key=lambda d: d.get("timestamp_ms") or 0,
    )
    latest = days_sorted[-1]
    daily_flow = float(latest.get("total_flow_usd", 0.0))

    # Берём последние 3 дня (если меньше — столько, сколько есть)
    last_n = days_sorted[-3:]
    rolling_total = float(
        sum(float(d.get("total_flow_usd", 0.0)) for d in last_n)
    )

    latest_sign = _sign_from_value(daily_flow)
    rolling_sign = _sign_from_value(rolling_total)

    # Сигнал для Decision Engine (простая логика)
    net_3d = rolling_total
    if net_3d >= 150_000_000:
        signal = "heavy_inflow"
    elif net_3d <= -150_000_000:
        signal = "heavy_outflow"
    elif net_3d >= 30_000_000:
        signal = "bullish"
    elif net_3d <= -30_000_000:
        signal = "bearish"
    else:
        signal = "neutral"

    etp_summary: Dict[str, Any] = {
        "latest": {
            "date_display": latest.get("date_display"),
            "date_iso": latest.get("date_iso"),
            "timestamp_ms": latest.get("timestamp_ms"),
            "total_flow_usd": daily_flow,
            "sign": latest_sign,
        },
        "rolling_total_flow_usd": rolling_total,
        "rolling_sign": rolling_sign,
        # поля, которые использует Decision Engine
        "net_flow_3d_usd": net_3d,
        "signal": signal,
    }
    return etp_summary


def _build_liq_summary(base_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Забираем краткий итог по ликвидациям из data/btc_liq_map.json

    btc_liq_map.json (текущая структура):
    {
      "symbol": "BTC",
      "source": "...",
      "captured_at_iso": "...",
      "captured_at_ms": ...,
      "current_price": ...,
      "zones": [...],
      "summary": {...},
      "history": [...],
      "latest": {
        "captured_at_iso": "...",
        "captured_at_ms": ...,
        "current_price": ...,
        "zones": [...],
        "summary": {
          "dominant_side": "...",
          "upside_focus_zone": "...",
          "downside_focus_zone": "...",
          "comment": "..."
        }
      }
    }
    """
    liq_path = base_dir / "data" / "btc_liq_map.json"
    data = _safe_load_json(liq_path, {})
    if not data:
        return None

    latest = data.get("latest") or data
    summary = (latest.get("summary") or data.get("summary") or {}) or {}

    liq_summary: Dict[str, Any] = {
        "captured_at_iso": latest.get("captured_at_iso"),
        "captured_at_ms": latest.get("captured_at_ms"),
        "current_price": latest.get("current_price"),
        "dominant_side": summary.get("dominant_side", "neutral"),
        "upside_focus_zone": summary.get("upside_focus_zone"),
        "downside_focus_zone": summary.get("downside_focus_zone"),
        "comment": summary.get("comment"),
    }
    return liq_summary


def build_market_flow(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Собирает/обновляет агрегированный flow для BTC:

    - пытается загрузить существующий data/btc_flow.json;
    - если файла нет → строит минимальный flow из snapshot;
    - обновляет symbol/timestamp из snapshot;
    - встраивает:
        - etp_summary (из btc_etp_flow.json),
        - liq_summary (из btc_liq_map.json);
    - сохраняет обновлённый btc_flow.json;
    - возвращает flow (используется дашбордом и Decision Engine).
    """
    base_dir = get_base_dir()
    flow_path = base_dir / "data" / "btc_flow.json"

    # 1) Базовый flow (из файла или из snapshot)
    flow = _safe_load_json(flow_path, {})
    if not isinstance(flow, dict):
        flow = {}

    if not flow:
        flow = _build_basic_flow_from_snapshot(snapshot)
    else:
        # обновляем базовые поля из snapshot
        if snapshot.get("symbol"):
            flow["symbol"] = snapshot.get("symbol")
        if snapshot.get("timestamp_iso"):
            flow["timestamp_iso"] = snapshot.get("timestamp_iso")

    # 2) ETF summary
    etp_summary = _build_etp_summary(base_dir)
    if etp_summary is not None:
        flow["etp_summary"] = etp_summary

    # 3) Liquidations summary
    liq_summary = _build_liq_summary(base_dir)
    if liq_summary is not None:
        flow["liq_summary"] = liq_summary

    # 3.1) Crowd bias and trap index
    flow["crowd"] = _compute_crowd_bias(snapshot)
    flow["crowd_trap_index"] = _compute_trap_index(
        flow["crowd"]["bias"], liq_summary
    )

    # 3.2) News sentiment
    sentiment = _load_news_sentiment(base_dir)
    if sentiment:
        flow["news_sentiment"] = sentiment

    # 3.3) Derivatives snapshot from snapshot.derivatives
    derivatives = snapshot.get("derivatives") or {}
    if derivatives:
        flow["derivatives"] = derivatives

    # 3.4) Warnings and risk scoring
    flow["warnings"] = _build_warnings(flow, snapshot)
    flow["risk"] = _compute_risk_block(snapshot, flow)

    # 3.5) Alignment score combines structure + flow supports
    crowd_score = float(flow.get("crowd", {}).get("score", 0.5) or 0.5)
    etp_signal = (etp_summary or {}).get("signal")
    etp_bonus = 0.05 if etp_signal in {"bullish", "heavy_inflow"} else -0.05 if etp_signal in {"bearish", "heavy_outflow"} else 0.0
    flow["alignment_score"] = round(_clamp(crowd_score + etp_bonus), 3)

    # 4) Если нет reasons — соберём простое текстовое резюме
    if not flow.get("reasons"):
        reasons: List[str] = []
        ct = (flow.get("crowd_trend") or "").lower()
        if ct:
            reasons.append(f"crowd_{ct}")
        vr = flow.get("volatility_regime")
        if vr:
            reasons.append(f"vol_{vr}")
        if etp_summary:
            rs = etp_summary.get("rolling_sign")
            if rs and rs != "flat":
                reasons.append(f"etp_{rs}")
        if liq_summary:
            ds = (liq_summary.get("dominant_side") or "").lower()
            if ds and ds != "neutral":
                reasons.append(f"liq_{ds}")
        flow["reasons"] = reasons

    # 5) Сохраняем обновлённый flow на диск (для историй/отладки)
    try:
        flow_path.parent.mkdir(parents=True, exist_ok=True)
        with flow_path.open("w", encoding="utf-8") as f:
            json.dump(flow, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save btc_flow.json: %s", e)

    return flow
