-- Add explicit PnL columns to equity_curve to match application model
ALTER TABLE equity_curve
    ADD COLUMN IF NOT EXISTS realized_pnl DECIMAL(20, 8) NULL AFTER balance_usdt,
    ADD COLUMN IF NOT EXISTS unrealized_pnl DECIMAL(20, 8) NULL AFTER realized_pnl,
    ADD COLUMN IF NOT EXISTS daily_pnl DECIMAL(20, 8) NULL AFTER unrealized_pnl,
    ADD COLUMN IF NOT EXISTS weekly_pnl DECIMAL(20, 8) NULL AFTER daily_pnl;

-- Backfill data from legacy *_usdt columns when present
UPDATE equity_curve
SET
    realized_pnl = COALESCE(realized_pnl, realized_pnl_usdt, 0),
    unrealized_pnl = COALESCE(unrealized_pnl, unrealized_pnl_usdt, 0),
    daily_pnl = COALESCE(daily_pnl, 0),
    weekly_pnl = COALESCE(weekly_pnl, 0);
