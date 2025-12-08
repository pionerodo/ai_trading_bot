from decimal import Decimal

from src.analytics_engine.backtesting import BacktestResult, simulate_equity


def test_simulate_equity_tracks_pnl():
    trades = [
        (Decimal("100"), Decimal("105")),
        (Decimal("105"), Decimal("90")),
    ]
    result = simulate_equity(
        trades,
        starting_equity=Decimal("1000"),
        commission_pct=Decimal("0.0005"),
        slippage_pct=Decimal("0.0005"),
    )
    assert isinstance(result, BacktestResult)
    assert result.trades == 2
    assert len(result.equity_curve) == 3
    # ensure equity moved from start but not zero
    assert result.equity_curve[0] == Decimal("1000")
    assert result.equity_curve[-1] != Decimal("1000")
    assert 0 <= result.win_rate <= 1
