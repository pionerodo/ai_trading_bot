import pytest

pytest.importorskip("yaml")

from src.core.config_loader import get_base_dir, load_config


def test_load_config_adds_trading_defaults():
    config = load_config()
    trading = config.get("trading")

    assert trading is not None
    assert trading["initial_equity_usd"] == 10000.0
    assert trading["max_risk_pct_per_trade"] == 0.01
    assert trading["max_daily_loss_pct"] == 0.05
    assert trading["position_size_cap_usd"] == 5000.0
    assert trading["assumed_stop_pct"] == 0.01


def test_get_base_dir_points_to_project_root():
    base_dir = get_base_dir()
    assert base_dir.name == "ai_trading_bot"
