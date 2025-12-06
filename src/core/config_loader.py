from pathlib import Path
from pathlib import Path
from typing import Any, Dict

import yaml

# /www/wwwroot/ai-hedge.cryptobavaro.online/ai_trading_bot
_BASE_DIR = Path(__file__).resolve().parents[2]


def get_base_dir() -> Path:
    return _BASE_DIR


def load_config() -> Dict[str, Any]:
    """
    Загружаем YAML-конфиг и добавляем дефолты для блока trading,
    не ломая существующую структуру.
    """
    config_path = _BASE_DIR / "config" / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        data = {}

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
