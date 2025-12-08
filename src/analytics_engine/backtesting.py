"""Lightweight backtesting helpers for local validation."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Tuple


@dataclass
class BacktestResult:
    equity_curve: List[Decimal]
    pnl_curve: List[Decimal]
    trades: int
    win_rate: float


def simulate_equity(
    trades: Iterable[Tuple[Decimal, Decimal]],
    *,
    starting_equity: Decimal,
    commission_pct: Decimal,
    slippage_pct: Decimal,
) -> BacktestResult:
    """
    Very small deterministic simulator: trades is an iterable of tuples
    (entry_price, exit_price). We assume unit quantity and apply commission +
    slippage both ways. Suitable for smoke-tests and CI, not production.
    """

    equity = starting_equity
    equity_curve: List[Decimal] = [equity]
    pnl_curve: List[Decimal] = []
    wins = 0
    total = 0

    for entry, exit_ in trades:
        total += 1
        gross_return = (exit_ - entry) / entry
        total_fees = commission_pct * 2 + slippage_pct * 2
        net_return = gross_return - total_fees
        pnl = equity * net_return
        if pnl > 0:
            wins += 1
        equity += pnl
        equity_curve.append(equity)
        pnl_curve.append(pnl)

    win_rate = float(wins) / total if total else 0.0
    return BacktestResult(equity_curve=equity_curve, pnl_curve=pnl_curve, trades=total, win_rate=win_rate)
