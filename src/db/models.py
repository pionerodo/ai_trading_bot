from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    Date,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    JSON,
    func,
)
from sqlalchemy.orm import synonym

from .session import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uix_candles_sto"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(DateTime, nullable=False)
    close_time = Column(DateTime, nullable=False)
    open_price = Column("open_price", DECIMAL(20, 8), nullable=False)
    high_price = Column("high_price", DECIMAL(20, 8), nullable=False)
    low_price = Column("low_price", DECIMAL(20, 8), nullable=False)
    close_price = Column("close_price", DECIMAL(20, 8), nullable=False)
    volume = Column(DECIMAL(28, 12), nullable=False)
    quote_volume = Column(DECIMAL(28, 12))
    trades_count = Column(BigInteger)

    # Backward compatible aliases used by older analytics helpers
    open = synonym("open_price")
    high = synonym("high_price")
    low = synonym("low_price")
    close = synonym("close_price")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uix_snapshots_symbol_ts"),
        Index("idx_snapshots_ts", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    price = Column(DECIMAL(20, 8), nullable=False)
    session_json = Column(JSON)
    market_structure_json = Column(JSON)
    momentum_json = Column(JSON)
    volatility_json = Column(JSON)
    enriched_candles_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uix_flows_symbol_ts"),
        Index("idx_flows_ts", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    derivatives_json = Column(JSON)
    etp_summary_json = Column(JSON)
    liquidation_json = Column(JSON)
    crowd_json = Column(JSON)
    trap_index_json = Column(JSON)
    news_sentiment_json = Column(JSON)
    warnings_json = Column(JSON)
    risk_global_score = Column(DECIMAL(10, 8))
    risk_mode = Column(String(32))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uix_decisions_symbol_ts"),
        Index("idx_decisions_ts", "timestamp"),
        Index("idx_decisions_action", "action"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    action = Column(Enum("long", "short", "flat"), nullable=False)
    reason = Column(String(255), nullable=False)
    entry_min_price = Column(DECIMAL(20, 8))
    entry_max_price = Column(DECIMAL(20, 8))
    sl_price = Column(DECIMAL(20, 8))
    tp1_price = Column(DECIMAL(20, 8))
    tp2_price = Column(DECIMAL(20, 8))
    liq_tp_zone_id = Column(String(64))
    risk_level = Column(Integer, nullable=False, default=0)
    position_size_usdt = Column(DECIMAL(20, 8), nullable=False, default=0)
    leverage = Column(DECIMAL(10, 4), nullable=False, default=0)
    confidence = Column(DECIMAL(10, 8), nullable=False, default=0)
    risk_checks_json = Column(JSON)
    snapshot_id = Column(BigInteger)
    flow_id = Column(BigInteger)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class LiquidationZone(Base):
    __tablename__ = "liquidation_zones"
    __table_args__ = (
        Index("idx_liq_zone_symbol_capture", "symbol", "captured_at_utc"),
        Index("idx_liq_zone_cluster", "cluster_id", "captured_at_utc"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    source = Column(String(64))
    captured_at_utc = Column(DateTime, nullable=False)
    cluster_id = Column(String(64), nullable=False)
    side = Column(Enum("long", "short"), nullable=False)
    price_level = Column(DECIMAL(20, 8), nullable=False)
    strength_score = Column(DECIMAL(10, 8))
    size_btc = Column(DECIMAL(20, 8))
    comment = Column(String(255))


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("idx_positions_symbol_status", "symbol", "status"),
        Index("idx_positions_opened_at", "opened_at_utc"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum("long", "short"), nullable=False)
    status = Column(Enum("open", "closed"), nullable=False, default="open")

    entry_price = Column(DECIMAL(20, 8), nullable=False)
    avg_entry_price = Column(DECIMAL(20, 8), nullable=False)
    size = Column(DECIMAL(20, 8), nullable=False)
    max_size = Column(DECIMAL(20, 8))
    sl_price = Column(DECIMAL(20, 8))
    tp1_price = Column(DECIMAL(20, 8))
    tp2_price = Column(DECIMAL(20, 8))

    opened_at_utc = Column(DateTime, nullable=False)
    closed_at_utc = Column(DateTime)

    pnl_usdt = Column(DECIMAL(20, 8))
    pnl_pct = Column(DECIMAL(20, 8))

    tp1_hit = Column(Boolean, nullable=False, default=False)
    tp2_hit = Column(Boolean, nullable=False, default=False)
    liq_exit_used = Column(Boolean, nullable=False, default=False)

    risk_mode_at_open = Column(String(32))
    position_management_json = Column(JSON)
    decision_id = Column(BigInteger)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_orders_client_order"),
        Index("idx_orders_decision", "decision_id"),
        Index("idx_orders_symbol_status", "symbol", "status"),
        Index("idx_orders_exchange_order", "exchange_order_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange_order_id = Column(BigInteger)
    client_order_id = Column(String(64), nullable=False)
    symbol = Column(String(20), nullable=False)
    role = Column(Enum("entry", "sl", "tp1", "tp2", "liq_exit", "manual_exit"), nullable=False)
    side = Column(Enum("buy", "sell"), nullable=False)
    order_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    reason_code = Column(String(64))
    decision_id = Column(BigInteger)
    position_id = Column(BigInteger)
    price = Column(DECIMAL(20, 8))
    stop_price = Column(DECIMAL(20, 8))
    orig_qty = Column(DECIMAL(20, 8), nullable=False)
    executed_qty = Column(DECIMAL(20, 8), nullable=False, default=0)
    avg_fill_price = Column(DECIMAL(20, 8))
    created_at_utc = Column(DateTime, nullable=False, server_default=func.now())
    updated_at_utc = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    json_data = Column(JSON)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trades_position", "position_id"),
        Index("idx_trades_decision", "decision_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    position_id = Column(BigInteger)
    decision_id = Column(BigInteger)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum("long", "short"), nullable=False)

    entry_price = Column(DECIMAL(20, 8), nullable=False)
    avg_entry_price = Column(DECIMAL(20, 8))
    exit_price = Column(DECIMAL(20, 8), nullable=False)
    avg_exit_price = Column(DECIMAL(20, 8))
    quantity = Column(DECIMAL(20, 8), nullable=False)

    pnl_usdt = Column(DECIMAL(20, 8))
    pnl_pct = Column(DECIMAL(20, 8))

    opened_at_utc = Column(DateTime, nullable=False)
    closed_at_utc = Column(DateTime, nullable=False)

    exit_reason = Column(String(32))
    tp1_hit = Column(Boolean, nullable=False, default=False)
    tp2_hit = Column(Boolean, nullable=False, default=False)
    position_management_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Log(Base):
    __tablename__ = "logs"
    __table_args__ = (
        Index("idx_logs_ts", "timestamp"),
        Index("idx_logs_level", "level"),
        Index("idx_logs_source", "source"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    level = Column(String(16), nullable=False)
    source = Column(String(64), nullable=False)
    message = Column(String(1024), nullable=False)
    context = Column(JSON)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (
        Index("idx_risk_events_ts", "timestamp"),
        Index("idx_risk_events_symbol", "symbol"),
        Index("idx_risk_events_type", "event_type"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    event_type = Column(String(64), nullable=False)
    symbol = Column(String(20), nullable=False)
    details = Column(String(1024), nullable=False)
    details_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class EquityCurve(Base):
    __tablename__ = "equity_curve"
    __table_args__ = (
        Index("idx_equity_timestamp", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    symbol = Column(String(20), nullable=False, default="BTCUSDT")
    equity_usdt = Column(DECIMAL(20, 8), nullable=False)
    balance_usdt = Column(DECIMAL(20, 8))
    unrealized_pnl = Column(DECIMAL(20, 8))
    realized_pnl = Column(DECIMAL(20, 8))
    daily_pnl = Column(DECIMAL(20, 8))
    weekly_pnl = Column(DECIMAL(20, 8))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
