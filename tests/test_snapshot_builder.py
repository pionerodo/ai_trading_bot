import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics_engine.snapshot_builder import build_btc_snapshot, persist_snapshot
from src.db.models import Base


def test_build_snapshot_prefers_db_data(tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    payload = {
        "symbol": "BTCUSDT",
        "timestamp": datetime.utcnow().isoformat(),
        "price": 1.5,
        "candles": {
            "1m": {"open": 1, "high": 2, "low": 0.5, "close": 1.5},
        },
    }

    with Session() as session:
        persist_snapshot(session, payload)
        result = build_btc_snapshot(session)

    assert result["symbol"] == "BTCUSDT"
    assert result["timeframes"]["1m"]["last_close"] == 1.5
    assert "timestamp_iso" in result


def test_build_snapshot_from_file(tmp_path):
    snapshot_path = tmp_path / "btc_snapshot.json"
    snapshot_json = {
        "symbol": "BTCUSDT",
        "timestamp": "2024-01-01T00:00:00",
        "candles": {"5m": {"open": 10, "high": 12, "low": 9, "close": 11}},
    }
    snapshot_path.write_text(json.dumps(snapshot_json))

    result = build_btc_snapshot(db=None, snapshot_path=snapshot_path)
    assert result["timeframes"]["5m"]["last_high"] == 12
    assert result["timestamp_iso"] == "2024-01-01T00:00:00"
