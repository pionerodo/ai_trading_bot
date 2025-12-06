import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.models import EquityCurve, Trade

logger = logging.getLogger(__name__)


def _as_decimal(value, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _get_env_decimal(name: str, default: str) -> Decimal:
    raw = os.getenv(name)
    if raw is None:
        return Decimal(default)
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return Decimal(default)


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class RiskStateService:
    """Aggregates global risk state purely from DB data."""

    def __init__(
        self,
        db_session_factory,
        *,
        max_daily_dd_pct: Optional[Decimal] = None,
        max_weekly_dd_pct: Optional[Decimal] = None,
        max_trades_per_day: Optional[int] = None,
        max_losing_streak: Optional[int] = None,
        starting_equity_usdt: Optional[Decimal] = None,
    ):
        self.db_session_factory = db_session_factory
        self.max_daily_dd_pct = max_daily_dd_pct or _get_env_decimal("MAX_DAILY_DD_PCT", "5")
        self.max_weekly_dd_pct = max_weekly_dd_pct or _get_env_decimal("MAX_WEEKLY_DD_PCT", "10")
        self.max_trades_per_day = max_trades_per_day or _get_env_int("MAX_TRADES_PER_DAY", 5)
        self.max_losing_streak = max_losing_streak or _get_env_int("MAX_LOSING_STREAK", 3)
        self.starting_equity_usdt = starting_equity_usdt or _get_env_decimal(
            "STARTING_EQUITY_USDT", "10000"
        )

    def get_current_state(self, symbol: str, now_utc: datetime) -> Dict:
        day_start = datetime(now_utc.year, now_utc.month, now_utc.day)
        week_start = now_utc - timedelta(days=7)
        with self.db_session_factory() as session:  # type: Session
            base_equity = self._get_base_equity(session, symbol)

            daily_pnl = self._sum_trades_since(session, symbol, day_start)
            weekly_pnl = self._sum_trades_since(session, symbol, week_start)
            trades_today = self._count_trades_since(session, symbol, day_start)
            losing_streak = self._compute_losing_streak(session, symbol)

        daily_dd_pct = self._drawdown_pct(daily_pnl, base_equity)
        weekly_dd_pct = self._drawdown_pct(weekly_pnl, base_equity)

        can_trade = True
        reasons: List[str] = []
        risk_mode = "NORMAL"

        if daily_dd_pct > self.max_daily_dd_pct:
            can_trade = False
            risk_mode = "OFF"
            reasons.append(f"Daily DD {daily_dd_pct:.2f}% exceeds limit {self.max_daily_dd_pct}%")

        if weekly_dd_pct > self.max_weekly_dd_pct:
            can_trade = False
            risk_mode = "OFF"
            reasons.append(f"Weekly DD {weekly_dd_pct:.2f}% exceeds limit {self.max_weekly_dd_pct}%")

        if trades_today >= self.max_trades_per_day:
            can_trade = False
            risk_mode = "OFF"
            reasons.append(
                f"Trades today {trades_today} reach/max limit {self.max_trades_per_day}"
            )

        if losing_streak >= self.max_losing_streak:
            can_trade = False
            risk_mode = "OFF"
            reasons.append(
                f"Losing streak {losing_streak} exceeds limit {self.max_losing_streak}"
            )

        if can_trade and (daily_dd_pct > self.max_daily_dd_pct * Decimal("0.8")):
            risk_mode = "SAFE"

        state = {
            "can_trade": can_trade,
            "reasons": reasons,
            "risk_mode": risk_mode,
            "daily_dd_pct": daily_dd_pct,
            "weekly_dd_pct": weekly_dd_pct,
            "trades_today": trades_today,
            "losing_streak": losing_streak,
        }
        logger.debug("Risk state computed: %s", state)
        return state

    def update_equity_after_trade(self, trade: Trade) -> None:
        if trade is None:
            return
        with self.db_session_factory() as session:  # type: Session
            base_equity = self._get_base_equity(session, trade.symbol)
            pnl = _as_decimal(trade.pnl_usdt)
            new_equity = base_equity + pnl
            day_start = datetime(trade.closed_at_utc.year, trade.closed_at_utc.month, trade.closed_at_utc.day)
            week_start = trade.closed_at_utc - timedelta(days=7)
            daily_pnl = self._sum_trades_since(session, trade.symbol, day_start)
            weekly_pnl = self._sum_trades_since(session, trade.symbol, week_start)

            row = EquityCurve(
                timestamp=trade.closed_at_utc,
                symbol=trade.symbol,
                equity_usdt=new_equity,
                realized_pnl=pnl,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
            )
            session.add(row)
            session.commit()
            logger.info(
                "Equity updated after trade %s: equity=%s daily_pnl=%s weekly_pnl=%s",
                trade.id,
                new_equity,
                daily_pnl,
                weekly_pnl,
            )

    def _get_base_equity(self, session: Session, symbol: str) -> Decimal:
        latest = (
            session.query(EquityCurve)
            .filter(EquityCurve.symbol == symbol)
            .order_by(EquityCurve.timestamp.desc())
            .first()
        )
        if latest:
            return _as_decimal(latest.equity_usdt)
        return self.starting_equity_usdt

    def _sum_trades_since(self, session: Session, symbol: str, since: datetime) -> Decimal:
        rows = (
            session.query(Trade)
            .filter(Trade.symbol == symbol, Trade.closed_at_utc >= since)
            .all()
        )
        total = Decimal("0")
        for row in rows:
            total += _as_decimal(row.pnl_usdt)
        return total

    def _count_trades_since(self, session: Session, symbol: str, since: datetime) -> int:
        return (
            session.query(Trade)
            .filter(Trade.symbol == symbol, Trade.closed_at_utc >= since)
            .count()
        )

    def _compute_losing_streak(self, session: Session, symbol: str) -> int:
        rows = (
            session.query(Trade)
            .filter(Trade.symbol == symbol)
            .order_by(Trade.closed_at_utc.desc())
            .limit(50)
            .all()
        )
        streak = 0
        for row in rows:
            pnl = _as_decimal(row.pnl_usdt)
            if pnl < 0:
                streak += 1
            else:
                break
        return streak

    def _drawdown_pct(self, pnl: Decimal, equity: Decimal) -> Decimal:
        if equity <= 0:
            return Decimal("0")
        if pnl >= 0:
            return Decimal("0")
        return abs(pnl) / equity * Decimal("100")

