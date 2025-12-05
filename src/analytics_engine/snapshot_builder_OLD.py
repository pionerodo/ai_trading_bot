import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from src.core.config_loader import load_config, get_base_dir
from src.db.models import Candle


logger = logging.getLogger("ai_trading_bot")


def _analyze_tf(candles: List[Candle]) -> Dict[str, Any]:
    """
    Простейший анализ по ТФ + расширение:
    - последнее закрытие
    - изменение к предыдущей свече
    - направление (up/down/flat)
    - диапазон high-low за последние N свечей
    - средняя волатильность (avg_range_pct)
    - сила тренда (trend_strength_score)
    - режим волатильности (low/normal/high)
    """
    if len(candles) < 2:
        return {"status": "not_enough_data"}

    last = candles[0]
    prev = candles[1]

    last_close = float(last.close)
    prev_close = float(prev.close)

    change_abs = last_close - prev_close
    change_pct = (change_abs / prev_close) * 100 if prev_close != 0 else 0.0

    eps = 0.05  # 0.05% порог для "flat"
    if change_pct > eps:
        direction = "up"
    elif change_pct < -eps:
        direction = "down"
    else:
        direction = "flat"

    # диапазон по N последним свечам
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]

    range_max = max(highs)
    range_min = min(lows)
    range_abs = range_max - range_min
    range_pct = (range_abs / last_close) * 100 if last_close != 0 else 0.0

    # --- доп. метрики волатильности ---
    # средний % диапазон по последним N свечам
    vol_window = min(20, len(candles))
    per_bar_ranges = []
    for c in candles[:vol_window]:
        close_val = float(c.close)
        if close_val == 0:
            continue
        r_abs = float(c.high) - float(c.low)
        r_pct = (r_abs / close_val) * 100
        per_bar_ranges.append(r_pct)

    if per_bar_ranges:
        avg_range_pct = sum(per_bar_ranges) / len(per_bar_ranges)
    else:
        avg_range_pct = 0.0

    # диапазон текущей свечи
    last_range_abs = float(last.high) - float(last.low)
    last_range_pct = (last_range_abs / last_close) * 100 if last_close != 0 else 0.0

    # классификация режима волатильности
    # (пороговые значения эмпирические, потом можно подстроить)
    if avg_range_pct < 0.15:
        volatility_label = "low"
    elif avg_range_pct < 0.6:
        volatility_label = "normal"
    else:
        volatility_label = "high"

    # сила тренда относительно волатильности
    denom = avg_range_pct if avg_range_pct > 0 else 0.1
    trend_strength_score = abs(change_pct) / denom
    if trend_strength_score > 3.0:
        trend_strength_score = 3.0

    return {
        "last_close": last_close,
        "prev_close": prev_close,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "direction": direction,
        "range_high": range_max,
        "range_low": range_min,
        "range_pct": range_pct,
        "bars_analyzed": len(candles),
        "last_open_time_ms": int(last.open_time),
        # новые поля
        "avg_range_pct": avg_range_pct,
        "last_range_pct": last_range_pct,
        "volatility_label": volatility_label,
        "trend_strength_score": trend_strength_score,
    }


def build_btc_snapshot(db: Session) -> Dict[str, Any]:
    """
    Собирает btc_snapshot по всем ТФ из config.analysis.timeframes
    и сохраняет в data/btc_snapshot.json.
    """
    config = load_config()
    base_dir: Path = get_base_dir()

    symbol = config.get("analysis", {}).get("symbol", "BTCUSDT")
    timeframes = config.get("analysis", {}).get("timeframes", ["1m", "5m", "15m", "1h"])

    snapshot: Dict[str, Any] = {
        "symbol": symbol,
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "timeframes": {},
    }

    for tf in timeframes:
        candles = (
            db.query(Candle)
            .filter(Candle.symbol == symbol, Candle.timeframe == tf)
            .order_by(Candle.open_time.desc())
            .limit(120)
            .all()
        )

        analysis = _analyze_tf(candles)
        snapshot["timeframes"][tf] = analysis

    # путь к файлу
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = data_dir / "btc_snapshot.json"

    with snapshot_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info("btc_snapshot.json updated at %s", snapshot_path)

    return snapshot
