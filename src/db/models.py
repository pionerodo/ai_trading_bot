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
    risk_level = Column(Integer, nullable=False, default=0)
    position_size_usdt = Column(DECIMAL(20, 8), nullable=False, default=0)
    leverage = Column(DECIMAL(10, 4), nullable=False, default=0)
    confidence = Column(DECIMAL(10, 8), nullable=False, default=0)
    risk_checks_json = Column(JSON)
    snapshot_id = Column(BigInteger)
    flow_id = Column(BigInteger)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_orders_client_order"),
        Index("idx_orders_decision", "decision_id"),
        Index("idx_orders_symbol_status", "symbol", "status"),
        Index("idx_orders_exchange_order", "binance_order_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    binance_order_id = Column(BigInteger)
    client_order_id = Column(String(64), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum("BUY", "SELL"), nullable=False)
    type = Column(String(32), nullable=False)
    time_in_force = Column(String(8))
    decision_id = Column(BigInteger)
    position_id = Column(BigInteger)
    status = Column(String(32), nullable=False)
    created_at_exchange = Column(DateTime)
    updated_at_exchange = Column(DateTime)
    price = Column(DECIMAL(20, 8), nullable=False)
    orig_qty = Column(DECIMAL(20, 8), nullable=False)
    executed_qty = Column(DECIMAL(20, 8), nullable=False, default=0)
    cumulative_quote = Column(DECIMAL(20, 8), nullable=False, default=0)
    is_entry = Column(Boolean, nullable=False, default=False)
    is_sl = Column(Boolean, nullable=False, default=False)
    is_tp = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    json_data = Column(JSON)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("idx_trades_order", "order_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(BigInteger, nullable=False)
    binance_trade_id = Column(BigInteger)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum("BUY", "SELL"), nullable=False)
    price = Column(DECIMAL(20, 8), nullable=False)
    qty = Column(DECIMAL(20, 8), nullable=False)
    quote_qty = Column(DECIMAL(20, 8), nullable=False)
    commission = Column(DECIMAL(20, 8))
    commission_asset = Column(String(16))
    realized_pnl = Column(DECIMAL(20, 8))
    exec_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
