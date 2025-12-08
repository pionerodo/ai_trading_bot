from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


# ---------------------------------------------------------------------------
#  BOT STATE (из дампа)
# ---------------------------------------------------------------------------


class BotState(Base):
    """
    Общий key–value стор для состояния бота.
    Таблица: bot_state
    """

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    value: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
#  CANDLES (исторические свечи)
# ---------------------------------------------------------------------------


class Candle(Base):
    """
    Таблица исторических свечей.
    Совмещает дамп и финальное ТЗ:
    - symbol, timeframe, open_time
    - OHLCV, quote_volume, trades, taker_buy_base/quote
    """

    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # время открытия свечи в ms / s (как в дампе)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    quote_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 8))
    trades: Mapped[Optional[int]] = mapped_column(Integer)

    taker_buy_base: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 8))
    taker_buy_quote: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 8))

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "open_time",
            name="uix_candles_symbol_tf_open_time",
        ),
        Index("idx_candles_symbol_tf", "symbol", "timeframe"),
    )


# ---------------------------------------------------------------------------
#  SNAPSHOTS (market snapshot JSON)
# ---------------------------------------------------------------------------


class Snapshot(Base):
    """
    Снимок рынка, который хранится в JSON.
    Таблица: snapshots
    """

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # исходный JSON-слепок рынка (btc_snapshot.json)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  FLOWS (btc_flow / btc_flow_history JSON)
# ---------------------------------------------------------------------------


class Flow(Base):
    """
    Агрегированное состояние потока / толпы по рынку.
    Таблица: flows
    """

    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    window_minutes: Mapped[int] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  NOTIFICATIONS (alerts routed to Telegram/email)
# ---------------------------------------------------------------------------


class Notification(Base):
    """Store alerting events for auditing and dashboards."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="log")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  LIQUIDATION ZONES (Hyperliquid / Coinglass)
# ---------------------------------------------------------------------------


class LiquidationZone(Base):
    """
    Предрасчитанные кластеры ликвидаций, чтобы Execution Engine
    мог быстро искать TP/SL зоны.
    Таблица: liquidation_zones
    """

    __tablename__ = "liquidation_zones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(
        Enum("long", "short", name="liq_zone_side"), nullable=False
    )

    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)

    comment: Mapped[Optional[str]] = mapped_column(String(255))

    source: Mapped[Optional[str]] = mapped_column(String(50))  # coinglass / hyperliquid

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  DECISIONS (ключевая таблица между Analysis и Execution)
# ---------------------------------------------------------------------------


class Decision(Base):
    """
    Решение AI / стратегии по инструменту.
    Комбинирует старый дамп и расширенное ТЗ.
    Таблица: decisions
    """

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # старое поле из дампа (BIGINT timestamp) – оставляем для совместимости
    timestamp: Mapped[Optional[int]] = mapped_column(BigInteger)

    # нормализованное время создания решения
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    # направление
    action: Mapped[str] = mapped_column(
        Enum("long", "short", "flat", name="decision_action"), nullable=False
    )

    reason: Mapped[Optional[str]] = mapped_column(String(255))

    # зона входа
    entry_min_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    entry_max_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))

    # стоп и цели
    sl_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    tp1_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    tp2_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))

    # связь с liq-зоной (если TP привязали к кластеру)
    liq_tp_zone_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("liquidation_zones.id")
    )
    liq_tp_zone: Mapped[Optional[LiquidationZone]] = relationship("LiquidationZone")

    # риск-метрики
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position_size_usdt: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    leverage: Mapped[Optional[float]] = mapped_column(Float)

    confidence: Mapped[Optional[float]] = mapped_column(Float)

    # подробный JSON с чек-листом риск-менеджера
    risk_checks_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    # ссылки на исходные snapshot / flow
    snapshot_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("snapshots.id")
    )
    flow_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("flows.id")
    )

    snapshot: Mapped[Optional[Snapshot]] = relationship("Snapshot")
    flow: Mapped[Optional[Flow]] = relationship("Flow")

    __table_args__ = (
        Index(
            "idx_decisions_symbol_created",
            "symbol",
            "created_at",
        ),
    )


# ---------------------------------------------------------------------------
#  POSITIONS (открытые позиции)
# ---------------------------------------------------------------------------


class Position(Base):
    """
    Текущее состояние позиции по инструменту.
    Таблица: positions
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    side: Mapped[str] = mapped_column(
        Enum("long", "short", name="position_side"), nullable=False
    )

    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)

    leverage: Mapped[Optional[float]] = mapped_column(Float)

    sl_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    tp1_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    tp2_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))

    decision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("decisions.id")
    )
    decision: Mapped[Optional[Decision]] = relationship("Decision")

    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
#  ORDERS (ордер-менеджер)
# ---------------------------------------------------------------------------


class Order(Base):
    """
    Все ордера, которыми оперирует Execution Engine.
    Таблица: orders
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(
        Enum("buy", "sell", name="order_side"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # limit / market / stop

    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    decision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("decisions.id")
    )
    position_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("positions.id")
    )

    decision: Mapped[Optional[Decision]] = relationship("Decision")
    position: Mapped[Optional[Position]] = relationship("Position")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# ---------------------------------------------------------------------------
#  TRADES (фактические сделки)
# ---------------------------------------------------------------------------


class Trade(Base):
    """
    Наполненные сделки по данным биржи.
    Таблица: trades
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    exchange_trade_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(
        Enum("buy", "sell", name="trade_side"), nullable=False
    )

    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)

    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    fee_asset: Mapped[Optional[str]] = mapped_column(String(10))

    order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("orders.id")
    )
    position_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("positions.id")
    )

    order: Mapped[Optional[Order]] = relationship("Order")
    position: Mapped[Optional[Position]] = relationship("Position")

    executed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  MARKET_FLOW (из дампа; простая сводка тренда)
# ---------------------------------------------------------------------------


class MarketFlow(Base):
    """
    Сводка тренда по символу/таймфрейму (историческое наследие).
    Таблица: market_flow (из SQL-дампа).
    """

    __tablename__ = "market_flow"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    trend: Mapped[str] = mapped_column(
        Enum("bullish", "bearish", "neutral", name="market_flow_trend"),
        nullable=False,
    )
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
#  LOGS (журнал исполнения)
# ---------------------------------------------------------------------------)


class Log(Base):
    """
    Высоко-уровневый лог исполнения для dashboard и отладки.
    Таблица: logs
    """

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), index=True)

    module: Mapped[Optional[str]] = mapped_column(String(100))
    function: Mapped[Optional[str]] = mapped_column(String(100))

    message: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
#  RISK_EVENTS (отдельный журнал риск-событий)
# ---------------------------------------------------------------------------


class RiskEvent(Base):
    """
    Лог важных риск-событий (фейл smoke-теста, проблемы с биржей и т.п.)
    Таблица: risk_events
    """

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), index=True)

    details: Mapped[Optional[str]] = mapped_column(Text)
    details_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
#  EQUITY_CURVE (P&L история)
# ---------------------------------------------------------------------------


class EquityCurve(Base):
    """
    История equity / P&L для анализа стратегий.
    Таблица: equity_curve
    """

    __tablename__ = "equity_curve"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    equity_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    balance_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    realized_pnl_usdt: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    unrealized_pnl_usdt: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
