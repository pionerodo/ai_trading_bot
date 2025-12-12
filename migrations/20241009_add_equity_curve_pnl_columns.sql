-- Add explicit PnL columns to equity_curve to match application model
ALTER TABLE equity_curve
    ADD COLUMN IF NOT EXISTS realized_pnl DECIMAL(20, 8) NULL AFTER balance_usdt,
    ADD COLUMN IF NOT EXISTS unrealized_pnl DECIMAL(20, 8) NULL AFTER realized_pnl,
    ADD COLUMN IF NOT EXISTS daily_pnl DECIMAL(20, 8) NULL AFTER unrealized_pnl,
    ADD COLUMN IF NOT EXISTS weekly_pnl DECIMAL(20, 8) NULL AFTER daily_pnl;

-- Backfill data from legacy *_usdt columns when present.
-- Not all databases have these columns, so use dynamic SQL guarded by INFORMATION_SCHEMA checks.
SET @has_realized_usdt := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'equity_curve'
      AND COLUMN_NAME = 'realized_pnl_usdt'
);

SET @has_unrealized_usdt := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'equity_curve'
      AND COLUMN_NAME = 'unrealized_pnl_usdt'
);

SET @update_sql := CASE
    WHEN @has_realized_usdt > 0 AND @has_unrealized_usdt > 0 THEN
        'UPDATE equity_curve\n' ||
        'SET\n' ||
        '    realized_pnl = COALESCE(realized_pnl, realized_pnl_usdt, 0),\n' ||
        '    unrealized_pnl = COALESCE(unrealized_pnl, unrealized_pnl_usdt, 0),\n' ||
        '    daily_pnl = COALESCE(daily_pnl, 0),\n' ||
        '    weekly_pnl = COALESCE(weekly_pnl, 0);'
    WHEN @has_realized_usdt > 0 THEN
        'UPDATE equity_curve\n' ||
        'SET\n' ||
        '    realized_pnl = COALESCE(realized_pnl, realized_pnl_usdt, 0),\n' ||
        '    unrealized_pnl = COALESCE(unrealized_pnl, 0),\n' ||
        '    daily_pnl = COALESCE(daily_pnl, 0),\n' ||
        '    weekly_pnl = COALESCE(weekly_pnl, 0);'
    WHEN @has_unrealized_usdt > 0 THEN
        'UPDATE equity_curve\n' ||
        'SET\n' ||
        '    realized_pnl = COALESCE(realized_pnl, 0),\n' ||
        '    unrealized_pnl = COALESCE(unrealized_pnl, unrealized_pnl_usdt, 0),\n' ||
        '    daily_pnl = COALESCE(daily_pnl, 0),\n' ||
        '    weekly_pnl = COALESCE(weekly_pnl, 0);'
    ELSE
        'UPDATE equity_curve\n' ||
        'SET\n' ||
        '    realized_pnl = COALESCE(realized_pnl, 0),\n' ||
        '    unrealized_pnl = COALESCE(unrealized_pnl, 0),\n' ||
        '    daily_pnl = COALESCE(daily_pnl, 0),\n' ||
        '    weekly_pnl = COALESCE(weekly_pnl, 0);'
END;

PREPARE stmt FROM @update_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
