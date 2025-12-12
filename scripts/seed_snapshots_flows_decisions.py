"""Seed snapshots, flows, and decisions tables with sample data.

Usage:
    python scripts/seed_snapshots_flows_decisions.py [--database-url <URL>]

If no URL is provided, the script tries DATABASE_URL env var, then the
config/database block, and finally falls back to a local SQLite file under
``db/ai_trading_bot_dev.sqlite``.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config_loader import load_config
from src.db.models import Base, Decision, Flow, Snapshot

DEFAULT_SYMBOL = "BTCUSDT"


def _build_mysql_url(config: Dict[str, Any]) -> str:
    db_cfg = config.get("database", {})
    user = db_cfg.get("user", "ai_trader")
    password = db_cfg.get("password", "")
    host = db_cfg.get("host", "127.0.0.1")
    port = db_cfg.get("port", 3306)
    name = db_cfg.get("name", "ai_trading_bot")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def resolve_database_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    try:
        cfg = load_config()
        return _build_mysql_url(cfg)
    except FileNotFoundError:
        pass

    sqlite_path = Path("db/ai_trading_bot_dev.sqlite")
    sqlite_path.parent.mkdir(exist_ok=True, parents=True)
    return f"sqlite:///{sqlite_path}"


def load_json(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return fallback


def seed(session: Session) -> None:
    snapshot_payload = load_json(
        Path("data/btc_liq_snapshot.json"),
        {
            "price": 90000,
            "volatility": {"atr": 1200},
            "structure": {"trend": "up"},
        },
    )
    now = datetime.utcnow()
    snapshot = Snapshot(
        symbol=DEFAULT_SYMBOL,
        timestamp=now,
        price=Decimal(str(snapshot_payload.get("price") or 0)),
        c_5m=Decimal(str(snapshot_payload.get("price") or 0)),
        candles_json=snapshot_payload.get("candles"),
        market_structure_json=snapshot_payload.get("structure"),
        momentum_json=snapshot_payload.get("momentum"),
        session_json=snapshot_payload.get("session"),
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)

    flow_payload = load_json(
        Path("data/btc_flow.json"),
        {
            "crowd_bias": "bullish",
            "trap_index": 0.21,
            "risk": {"global_score": 0.63},
        },
    )
    flow = Flow(
        symbol=DEFAULT_SYMBOL,
        payload=flow_payload,
        window_minutes=60,
    )
    session.add(flow)
    session.commit()
    session.refresh(flow)

    decision = Decision(
        symbol=DEFAULT_SYMBOL,
        action="long",
        reason="seeded sample",
        timestamp=int(now.timestamp()),
        created_at=now + timedelta(seconds=1),
        entry_min_price=snapshot_payload.get("price"),
        entry_max_price=snapshot_payload.get("price"),
        sl_price=(snapshot_payload.get("price") or 0) * 0.98,
        tp1_price=(snapshot_payload.get("price") or 0) * 1.01,
        tp2_price=(snapshot_payload.get("price") or 0) * 1.02,
        snapshot_id=snapshot.id,
        flow_id=flow.id,
        risk_level=1,
        confidence=flow_payload.get("risk", {}).get("global_score", 0.5),
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)

    print("Seeded records:")
    print(f"  Snapshot ID: {snapshot.id}")
    print(f"  Flow ID: {flow.id}")
    print(f"  Decision ID: {decision.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed snapshots/flows/decisions tables")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. If omitted, config/env/SQLite fallback is used.",
    )
    args = parser.parse_args()

    db_url = resolve_database_url(args.database_url)
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as session:
        seed(session)


if __name__ == "__main__":
    main()
