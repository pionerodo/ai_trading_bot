from sqlalchemy import (
    BigInteger,
    Column,
    DECIMAL,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    JSON,
)

from .session import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uix_candles_sto"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(BigInteger, nullable=False)
    open = Column(DECIMAL(20, 8), nullable=False)
    high = Column(DECIMAL(20, 8), nullable=False)
    low = Column(DECIMAL(20, 8), nullable=False)
    close = Column(DECIMAL(20, 8), nullable=False)
    volume = Column(DECIMAL(20, 8), nullable=False)
    close_time = Column(BigInteger, nullable=False)


class MarketFlow(Base):
    __tablename__ = "market_flow"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp_ms", name="uix_market_flow_st"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp_ms = Column(BigInteger, nullable=False)
    symbol = Column(String(20), nullable=False)
    crowd_sentiment = Column(Float)
    funding_rate = Column(Float)
    open_interest_change = Column(Float)
    liquidations_long = Column(Float)
    liquidations_short = Column(Float)
    risk_score = Column(Float)
    json_data = Column(JSON)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp_ms", name="uix_decisions_st"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp_ms = Column(BigInteger, nullable=False)
    symbol = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(Text)
    json_data = Column(JSON)


class Execution(Base):
    __tablename__ = "executions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp_ms = Column(BigInteger, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    price = Column(DECIMAL(20, 8), nullable=False)
    qty = Column(DECIMAL(20, 8), nullable=False)
    status = Column(String(20), nullable=False)
    exchange_order_id = Column(String(64))
    json_data = Column(JSON)
