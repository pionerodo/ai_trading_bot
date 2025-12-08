from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.db.models import Base, Decision, Flow, Snapshot


def test_snapshot_flow_decision_chain():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session() as session:
        snapshot = Snapshot(symbol="BTCUSDT", payload={"price": 100_000, "structure": "up"})
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        flow = Flow(
            symbol="BTCUSDT",
            payload={"crowd_bias": "bullish", "risk": {"global_score": 0.7}},
            window_minutes=30,
        )
        session.add(flow)
        session.commit()
        session.refresh(flow)

        decision = Decision(
            symbol="BTCUSDT",
            action="long",
            reason="smoke-test",
            timestamp=int(snapshot.created_at.timestamp()),
            snapshot_id=snapshot.id,
            flow_id=flow.id,
            entry_min_price=Decimal("99900"),
            entry_max_price=Decimal("100100"),
            sl_price=Decimal("99000"),
            tp1_price=Decimal("101500"),
            tp2_price=Decimal("103000"),
            risk_level=1,
            confidence=0.7,
        )
        session.add(decision)
        session.commit()

        stmt = (
            select(Decision)
            .options(selectinload(Decision.snapshot), selectinload(Decision.flow))
        )
        stored_decision = session.execute(stmt).scalar_one()

        assert stored_decision.action == "long"
        assert stored_decision.snapshot and stored_decision.snapshot.id == snapshot.id
        assert stored_decision.flow and stored_decision.flow.payload["crowd_bias"] == "bullish"
        assert stored_decision.created_at <= datetime.utcnow()
        assert stored_decision.timestamp == int(snapshot.created_at.timestamp())
