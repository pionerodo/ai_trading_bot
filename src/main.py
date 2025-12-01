import time
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.core.config_loader import load_config
from src.core.logging_config import setup_logging
from src.db.session import get_db
from src.db.models import Decision, Execution
from src.data_collector.candles_collector import sync_candles_for_timeframe
from src.analytics_engine.snapshot_builder import build_btc_snapshot
from src.analytics_engine.flow_builder import build_market_flow
from src.analytics_engine.decision_engine import compute_decision

# ⬇️ Binance (заглушка, без реальных запросов к бирже)
from src.services.binance_client import BinanceClient, load_binance_config


config = load_config()
logger = setup_logging(config)

app = FastAPI(
    title="AI Trading Showdown Bot",
    version="0.1.0",
    description="Autonomous BTCUSDT analysis and trading engine",
)

origins = [
    "https://cryptobavaro.online",
    "https://www.cryptobavaro.online",
    "https://capibaratrader.com",
    "https://www.capibaratrader.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    logger.info("AI Trading Showdown Bot starting up")
    logger.info(f"Environment: {config.get('app', {}).get('environment')}")
    logger.info(f"Symbol: {config.get('app', {}).get('symbol')}")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("AI Trading Showdown Bot shutting down")


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "ai-hedge",
        "time": datetime.utcnow().isoformat() + "Z",
        "environment": config.get("app", {}).get("environment"),
    }


# --------- DASHBOARD PAGE (из static/dashboard.html) ---------


@app.get("/dashboard")
def dashboard_page():
    base_dir = Path(__file__).resolve().parents[1]  # /.../ai_trading_bot
    file_path = base_dir / "static" / "dashboard.html"
    return FileResponse(file_path)


# --------- BASIC API ----------


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.api_route("/test-db", methods=["GET", "POST"])
def test_db(db: Session = Depends(get_db)):
    now_ms = int(time.time() * 1000)

    decision = Decision(
        timestamp_ms=now_ms,
        symbol="BTCUSDT",
        action="TEST",
        confidence=0.0,
        reason="DB health check",
        json_data={},
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    total = db.query(Decision).count()

    return {
        "inserted_id": decision.id,
        "total_decisions": total,
        "timestamp_ms": now_ms,
    }


# --------- DATA COLLECTION ----------


@app.api_route("/collect/candles", methods=["GET", "POST"])
def collect_candles(db: Session = Depends(get_db)):
    symbol = config.get("analysis", {}).get("symbol", "BTCUSDT")
    tfs = config.get("analysis", {}).get("timeframes", ["1m", "5m"])

    results = {}
    for tf in tfs:
        inserted, total = sync_candles_for_timeframe(
            db=db,
            symbol=symbol,
            timeframe=tf,
            limit=500,
        )
        results[tf] = {"inserted": inserted, "total": total}

    return {
        "symbol": symbol,
        "results": results,
        "time": datetime.utcnow().isoformat() + "Z",
    }


# --------- ANALYTICS ----------


@app.api_route("/analytics/snapshot", methods=["GET", "POST"])
def analytics_snapshot(db: Session = Depends(get_db)):
    return build_btc_snapshot(db)


@app.api_route("/analytics/flow", methods=["GET", "POST"])
def analytics_flow(db: Session = Depends(get_db)):
    snapshot = build_btc_snapshot(db)
    flow = build_market_flow(snapshot)
    return flow


# --------- DECISION ENGINE ----------


@app.api_route("/decision/next", methods=["GET", "POST"])
def decision_next(db: Session = Depends(get_db)):
    symbol = config.get("analysis", {}).get("symbol", "BTCUSDT")

    snapshot = build_btc_snapshot(db)
    flow = build_market_flow(snapshot)
    decision = compute_decision(snapshot, flow)

    from src.analytics_engine.decision_logger import log_decision
    decision_id = log_decision(db, symbol, decision)

    return {
        "decision_id": decision_id,
        "snapshot": snapshot,
        "flow": flow,
        "decision": decision,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/decision/history")
def decision_history(limit: int = 20, db: Session = Depends(get_db)):
    rows = (
        db.query(Decision)
        .order_by(Decision.timestamp_ms.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": d.id,
            "timestamp_ms": d.timestamp_ms,
            "symbol": d.symbol,
            "action": d.action,
            "confidence": d.confidence,
            "reason": d.reason,
            "json_data": d.json_data,
        }
        for d in rows
    ]


# --------- EXECUTION (виртуальный счёт, без Binance) ----------


@app.api_route("/execution/run", methods=["GET", "POST"])
def execution_run(db: Session = Depends(get_db)):
    symbol = config.get("analysis", {}).get("symbol", "BTCUSDT")

    snapshot = build_btc_snapshot(db)
    flow = build_market_flow(snapshot)
    decision = compute_decision(snapshot, flow)

    last_price = snapshot["timeframes"]["1m"]["last_close"]

    from src.analytics_engine.decision_logger import log_decision
    decision_id = log_decision(db, symbol, decision)

    from src.execution.executor import execute_decision
    state = execute_decision(db, decision, last_price)

    return {
        "decision_id": decision_id,
        "decision": decision,
        "price": last_price,
        "new_state": state,
        "time": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/state/current")
def state_current(db: Session = Depends(get_db)):
    from src.execution.state_manager import load_state
    state = load_state(db)
    return state


@app.get("/executions/history")
def executions_history(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Execution)
        .order_by(Execution.timestamp_ms.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": e.id,
            "timestamp_ms": e.timestamp_ms,
            "symbol": e.symbol,
            "side": e.side,
            "price": float(e.price),
            "qty": float(e.qty),
            "status": e.status,
            "exchange_order_id": e.exchange_order_id,
            "json_data": e.json_data,
        }
        for e in rows
    ]


# --------- DASHBOARD OVERVIEW ----------


@app.get("/dashboard/overview")
def dashboard_overview(
    dec_limit: int = 10,
    exec_limit: int = 20,
    db: Session = Depends(get_db),
):
    from src.execution.state_manager import load_state

    snapshot = build_btc_snapshot(db)
    flow = build_market_flow(snapshot)
    state = load_state(db)

    decisions = (
        db.query(Decision)
        .order_by(Decision.timestamp_ms.desc())
        .limit(dec_limit)
        .all()
    )
    executions = (
        db.query(Execution)
        .order_by(Execution.timestamp_ms.desc())
        .limit(exec_limit)
        .all()
    )

    decisions_list = [
        {
            "id": d.id,
            "timestamp_ms": d.timestamp_ms,
            "symbol": d.symbol,
            "action": d.action,
            "confidence": d.confidence,
            "reason": d.reason,
            "json_data": d.json_data,
        }
        for d in decisions
    ]

    executions_list = [
        {
            "id": e.id,
            "timestamp_ms": e.timestamp_ms,
            "symbol": e.symbol,
            "side": e.side,
            "price": float(e.price),
            "qty": float(e.qty),
            "status": e.status,
            "exchange_order_id": e.exchange_order_id,
            "json_data": e.json_data,
        }
        for e in executions
    ]

    return {
        "snapshot": snapshot,
        "flow": flow,
        "state": state,
        "decisions": decisions_list,
        "executions": executions_list,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# --------- BINANCE HEALTH (заглушка, без реальных запросов) ----------


@app.get("/binance/health")
def binance_health():
    """
    Безопасный health-check Binance.

    Все методы BinanceClient сейчас заглушки, поэтому:
    - реальных запросов к Binance нет;
    - статус возвращается из локальной логики.
    """
    bcfg = load_binance_config()
    client = BinanceClient(bcfg)

    status = client.get_account_status()

    return {
        "binance_enabled": bcfg.enabled,
        "testnet": bcfg.testnet,
        "status": status,
    }
