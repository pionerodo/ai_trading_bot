import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from src.core.config_loader import get_base_dir

logger = logging.getLogger("ai_trading_bot")

BASE_DIR: Path = get_base_dir()
DATA_DIR: Path = BASE_DIR / "data"

LIQ_SNAPSHOT_PATH = DATA_DIR / "btc_liq_snapshot.json"
LIQ_MAP_PATH = DATA_DIR / "btc_liq_map.json"


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        logger.warning("liq_map_updater: file not found: %s", path)
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("liq_map_updater: error reading %s: %s", path, e)
        return None


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("liq_map_updater: error writing %s: %s", path, e)


def _normalize_entry(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводим один снимок к единому формату для history.
    Ожидаем структуру, как в btc_liq_snapshot.json.
    """
    return {
        "captured_at_iso": snapshot.get("captured_at_iso"),
        "captured_at_ms": snapshot.get("captured_at_ms"),
        "current_price": snapshot.get("current_price"),
        "zones": snapshot.get("zones", []),
        "summary": snapshot.get("summary", {}),
    }


def _ensure_timestamp(snapshot: Dict[str, Any]) -> None:
    """
    Если в снапшоте нет captured_at_iso / captured_at_ms,
    ставим текущие значения (UTC).
    """
    ts_ms = snapshot.get("captured_at_ms")
    ts_iso = snapshot.get("captured_at_iso")

    if not ts_ms and not ts_iso:
        now = datetime.now(timezone.utc)
        ts_ms = int(now.timestamp() * 1000)
        ts_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        snapshot["captured_at_ms"] = ts_ms
        snapshot["captured_at_iso"] = ts_iso


def update_liq_map_from_snapshot() -> Optional[Dict[str, Any]]:
    """
    1) читает btc_liq_snapshot.json
    2) добавляет/обновляет запись в btc_liq_map.json (history + latest)
    3) дублирует поля latest на верхний уровень (для обратной совместимости)
    """
    snapshot = _load_json(LIQ_SNAPSHOT_PATH)
    if snapshot is None:
        logger.warning(
            "liq_map_updater: no snapshot, skip update (path=%s)",
            LIQ_SNAPSHOT_PATH,
        )
        return _load_json(LIQ_MAP_PATH)

    # если таймстампов нет — проставляем сейчас
    _ensure_timestamp(snapshot)

    entry = _normalize_entry(snapshot)
    ts_ms = entry.get("captured_at_ms")
    if ts_ms is None:
        logger.warning(
            "liq_map_updater: snapshot still has no captured_at_ms, skip"
        )
        return _load_json(LIQ_MAP_PATH)

    liq_map = _load_json(LIQ_MAP_PATH) or {
        "symbol": snapshot.get("symbol", "BTC"),
        "source": snapshot.get("source", "coinglass_hyperliquid_liq_map"),
        "history": [],
    }

    history: List[Dict[str, Any]] = liq_map.get("history", [])

    # обновляем / добавляем запись с таким же captured_at_ms
    replaced = False
    for i, h in enumerate(history):
        if h.get("captured_at_ms") == ts_ms:
            history[i] = entry
            replaced = True
            break
    if not replaced:
        history.append(entry)

    # сортировка по времени
    history.sort(key=lambda x: (x.get("captured_at_ms") or 0))

    liq_map["history"] = history
    latest = history[-1]
    liq_map["latest"] = latest

    # для совместимости со старым форматом
    for key in ("captured_at_iso", "captured_at_ms", "current_price", "zones", "summary"):
        liq_map[key] = latest.get(key)

    _save_json(LIQ_MAP_PATH, liq_map)
    logger.info(
        "liq_map_updater: btc_liq_map.json updated, history_len=%d, latest_ts=%s",
        len(history),
        latest.get("captured_at_iso") or latest.get("captured_at_ms"),
    )
    return liq_map


def get_latest_liq_summary(liq_map: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Короткий summary для использования в btc_flow.json / decision engine.
    """
    if liq_map is None:
        liq_map = _load_json(LIQ_MAP_PATH)
    if not liq_map:
        return None

    latest = liq_map.get("latest") or liq_map
    summary = latest.get("summary") or {}

    return {
        "current_price": latest.get("current_price"),
        "dominant_side": summary.get("dominant_side"),
        "upside_focus_zone": summary.get("upside_focus_zone"),
        "downside_focus_zone": summary.get("downside_focus_zone"),
        "comment": summary.get("comment"),
    }


if __name__ == "__main__":
    # удобный ручной запуск: python -m src.data_collector.liq_map_updater
    update_liq_map_from_snapshot()
