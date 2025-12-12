-- Migration: align snapshots table with production schema (timestamp/price + JSON blobs)
-- Target: MariaDB/MySQL 10.x
-- NOTE: run during maintenance with a verified backup.

-- 1) Ensure all required columns exist (keeps legacy payload for backfill)
ALTER TABLE snapshots
    ADD COLUMN IF NOT EXISTS `timestamp` DATETIME NULL AFTER `symbol`,
    ADD COLUMN IF NOT EXISTS `price` DECIMAL(20, 8) NULL AFTER `timestamp`,
    ADD COLUMN IF NOT EXISTS `o_5m` DECIMAL(20, 8) NULL AFTER `price`,
    ADD COLUMN IF NOT EXISTS `h_5m` DECIMAL(20, 8) NULL AFTER `o_5m`,
    ADD COLUMN IF NOT EXISTS `l_5m` DECIMAL(20, 8) NULL AFTER `h_5m`,
    ADD COLUMN IF NOT EXISTS `c_5m` DECIMAL(20, 8) NULL AFTER `l_5m`,
    ADD COLUMN IF NOT EXISTS `candles_json` LONGTEXT DEFAULT NULL CHECK (json_valid(`candles_json`)),
    ADD COLUMN IF NOT EXISTS `market_structure_json` LONGTEXT DEFAULT NULL CHECK (json_valid(`market_structure_json`)),
    ADD COLUMN IF NOT EXISTS `momentum_json` LONGTEXT DEFAULT NULL CHECK (json_valid(`momentum_json`)),
    ADD COLUMN IF NOT EXISTS `session_json` LONGTEXT DEFAULT NULL CHECK (json_valid(`session_json`)),
    ADD COLUMN IF NOT EXISTS `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS `payload` JSON NULL;

-- 2) Backfill from legacy payload JSON when available
UPDATE snapshots
SET
    `timestamp` = COALESCE(
        `timestamp`,
        JSON_UNQUOTE(JSON_EXTRACT(payload, '$.timestamp')),
        `created_at`
    ),
    `price` = COALESCE(
        `price`,
        JSON_EXTRACT(payload, '$.price'),
        JSON_EXTRACT(payload, '$.last_price')
    ),
    `o_5m` = COALESCE(
        `o_5m`,
        JSON_EXTRACT(payload, '$.candles."5m".open')
    ),
    `h_5m` = COALESCE(
        `h_5m`,
        JSON_EXTRACT(payload, '$.candles."5m".high')
    ),
    `l_5m` = COALESCE(
        `l_5m`,
        JSON_EXTRACT(payload, '$.candles."5m".low')
    ),
    `c_5m` = COALESCE(
        `c_5m`,
        JSON_EXTRACT(payload, '$.candles."5m".close')
    ),
    `candles_json` = COALESCE(`candles_json`, JSON_EXTRACT(payload, '$.candles')),
    `market_structure_json` = COALESCE(`market_structure_json`, JSON_EXTRACT(payload, '$.structure')),
    `momentum_json` = COALESCE(`momentum_json`, JSON_EXTRACT(payload, '$.momentum')),
    `session_json` = COALESCE(`session_json`, JSON_EXTRACT(payload, '$.session'));

-- 3) Enforce NOT NULL where required (set timestamp/price first if table was empty)
UPDATE snapshots
SET `timestamp` = IFNULL(`timestamp`, `created_at`),
    `price` = IFNULL(`price`, 0)
WHERE `timestamp` IS NULL OR `price` IS NULL;

ALTER TABLE snapshots
    MODIFY `timestamp` DATETIME NOT NULL,
    MODIFY `price` DECIMAL(20, 8) NOT NULL;

-- 4) Indexes/uniques aligned with application queries
ALTER TABLE snapshots
    ADD UNIQUE INDEX IF NOT EXISTS `uq_snapshots_symbol_ts` (`symbol`, `timestamp`),
    ADD INDEX IF NOT EXISTS `idx_snapshots_ts` (`timestamp`);
