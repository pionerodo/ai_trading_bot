from pathlib import Path
from typing import Any, Dict

import yaml

# /www/wwwroot/ai-hedge.cryptobavaro.online/ai_trading_bot
_BASE_DIR = Path(__file__).resolve().parents[2]


def get_base_dir() -> Path:
    return _BASE_DIR


def _safe_load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> Dict[str, Any]:
    """
    Загружаем YAML-конфиг и добавляем дефолты для блока trading,
    не ломая существующую структуру. Локальные секреты читаются из
    config/config.local.yaml поверх шаблонного config.yaml.
    """

    base_config_path = _BASE_DIR / "config" / "config.yaml"
    local_config_path = _BASE_DIR / "config" / "config.local.yaml"

    base_data = _safe_load_yaml(base_config_path)
    local_data = _safe_load_yaml(local_config_path)
    data = _merge_dicts(base_data, local_data)

    if not data:
        raise FileNotFoundError(
            f"Config file not found: {base_config_path} (and no local override)"
        )

    # Дефолтные настройки риска/торговли
    trading_defaults: Dict[str, Any] = {
        # Стартовый виртуальный депозит
        "initial_equity_usd": 10000.0,
        # Максимальный риск на сделку от текущего equity (1%)
        "max_risk_pct_per_trade": 0.01,
        # Максимальная дневная просадка от equity на начало дня (5%)
        "max_daily_loss_pct": 0.05,
        # Верхний предел виртуального объёма позиции в USD
        "position_size_cap_usd": 5000.0,
        # Предполагаемое расстояние до стопа по цене (1%)
        "assumed_stop_pct": 0.01,
    }

    trading = data.get("trading")
    if not isinstance(trading, dict):
        trading = {}
        data["trading"] = trading

    # Только добавляем отсутствующие ключи, не перезаписываем уже заданные
    for k, v in trading_defaults.items():
        trading.setdefault(k, v)

    return data
