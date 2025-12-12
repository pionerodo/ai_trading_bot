-- Migration: align `flows` and `market_flow` with docs/DATABASE_SCHEMA.md
-- Target DB: MariaDB 10.x
-- Run during maintenance window; back up tables first.

-- ------------------------------------------------------------
-- 1) flows – move to documented schema
-- ------------------------------------------------------------
DROP TABLE IF EXISTS flows_legacy_v2;
RENAME TABLE flows TO flows_legacy_v2;

-- Normalize legacy structure to avoid missing-column errors
ALTER TABLE flows_legacy_v2
    ADD COLUMN IF NOT EXISTS captured_at_utc DATETIME NULL,
    ADD COLUMN IF NOT EXISTS created_at DATETIME NULL;

-- Backfill captured_at_utc/created_at from available fields
UPDATE flows_legacy_v2
SET
    captured_at_utc = COALESCE(captured_at_utc, timestamp, created_at),
    created_at = COALESCE(created_at, captured_at_utc, timestamp, CURRENT_TIMESTAMP)
WHERE captured_at_utc IS NULL OR created_at IS NULL;

CREATE TABLE IF NOT EXISTS flows (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME NOT NULL,

    derivatives_json JSON NULL,
    etp_summary_json JSON NULL,
    liquidation_json JSON NULL,
    crowd_json JSON NULL,
    trap_index_json JSON NULL,
    news_sentiment_json JSON NULL,
    warnings_json JSON NULL,

    risk_global_score DECIMAL(10, 8) NULL,
    risk_mode VARCHAR(32) NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_flows_symbol_ts (symbol, timestamp),
    KEY idx_flows_ts (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO flows (
    id,
    symbol,
    timestamp,
    derivatives_json,
    etp_summary_json,
    liquidation_json,
    crowd_json,
    trap_index_json,
    news_sentiment_json,
    warnings_json,
    risk_global_score,
    risk_mode,
    created_at
)
SELECT
    id,
    symbol,
    COALESCE(timestamp, captured_at_utc, created_at) AS timestamp,
    NULL AS derivatives_json,
    etp_summary_json,
    liquidation_json,
    NULL AS crowd_json,
    NULL AS trap_index_json,
    NULL AS news_sentiment_json,
    warnings_json,
    risk_global_score,
    NULL AS risk_mode,
    COALESCE(created_at, captured_at_utc, timestamp, CURRENT_TIMESTAMP) AS created_at
FROM flows_legacy_v2
ORDER BY id;

-- ------------------------------------------------------------
-- 2) market_flow – align with timestamp_ms-based schema
-- ------------------------------------------------------------
DROP TABLE IF EXISTS market_flow_legacy_v2;
RENAME TABLE market_flow TO market_flow_legacy_v2;

CREATE TABLE IF NOT EXISTS market_flow (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    timestamp_ms BIGINT NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    crowd_sentiment FLOAT DEFAULT NULL,
    funding_rate FLOAT DEFAULT NULL,
    open_interest_change FLOAT DEFAULT NULL,
    liquidations_long FLOAT DEFAULT NULL,
    liquidations_short FLOAT DEFAULT NULL,
    risk_score FLOAT DEFAULT NULL,
    json_data JSON DEFAULT NULL,
    current_price DECIMAL(20,8) DEFAULT NULL,
    UNIQUE KEY uix_market_flow_symbol_ts (symbol, timestamp_ms),
    KEY idx_market_flow_symbol_ts (symbol, timestamp_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO market_flow (
    id,
    timestamp_ms,
    symbol,
    crowd_sentiment,
    funding_rate,
    open_interest_change,
    liquidations_long,
    liquidations_short,
    risk_score,
    json_data,
    current_price
)
SELECT
    id,
    timestamp_ms,
    symbol,
    crowd_sentiment,
    funding_rate,
    open_interest_change,
    liquidations_long,
    liquidations_short,
    risk_score,
    json_data,
    current_price
FROM market_flow_legacy_v2
ORDER BY id;
