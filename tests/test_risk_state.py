from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics_engine.risk_state import RiskStateService
from src.db.models import Base, Trade


def _build_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_risk_state_blocks_on_drawdown_and_trades():
    Session = _build_session_factory()
    now = datetime(2024, 1, 1, 12, 0, 0)
    day_start = datetime(now.year, now.month, now.day)

    with Session() as session:
        session.add(
            Trade(
                id=1,
                exchange_trade_id="t1",
                symbol="BTCUSDT",
                side="buy",
                price=Decimal("100"),
                quantity=Decimal("1"),
                executed_at=day_start + timedelta(hours=1),
                # no pnl_usdt column exists, so we keep meta in fee to test extractor fallback
                fee=Decimal("-10"),
            )
        )
        session.commit()

    service = RiskStateService(
        Session,
        max_daily_dd_pct=Decimal("0.5"),
        max_weekly_dd_pct=Decimal("0.5"),
        max_trades_per_day=1,
        max_losing_streak=1,
        starting_equity_usdt=Decimal("1000"),
    )

    state = service.get_current_state("BTCUSDT", now)
    assert state["can_trade"] is False
    assert state["risk_mode"] == "OFF"
    assert state["trades_today"] == 1


def test_risk_state_updates_equity_curve():
    Session = _build_session_factory()
    service = RiskStateService(Session, starting_equity_usdt=Decimal("500"))

    trade = Trade(
        id=2,
        exchange_trade_id="t2",
        symbol="BTCUSDT",
        side="sell",
        price=Decimal("105"),
        quantity=Decimal("1"),
        fee=Decimal("0"),
        executed_at=datetime(2024, 1, 2, 10, 0, 0),
    )
    # monkey patch pnl attribute to simulate realized result
    trade.pnl_usdt = Decimal("50")

    service.update_equity_after_trade(trade)

    with Session() as session:
        curve_rows = session.execute(
            text("SELECT equity_usdt, realized_pnl FROM equity_curve WHERE symbol='BTCUSDT'")
        ).all()
    assert curve_rows, "equity curve must be updated"
    assert Decimal(curve_rows[0][0]) == Decimal("550")
    assert Decimal(curve_rows[0][1]) == Decimal("50")
