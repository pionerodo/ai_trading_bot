-- Migration script: align production schema with docs/DATABASE_SCHEMA.md v1.0
-- Target DB: MariaDB 10.x
-- WARNING: запускайте в техобслуживание; держите полный backup и проверьте дубликаты, которые могут нарушить UNIQUE.

-- ------------------------------------------------------------
-- 0) Явный выбор базы
-- ------------------------------------------------------------
-- USE ai_trading_bot;

-- ------------------------------------------------------------
-- 1) Резервные копии ключевых таблиц (данные без индексов)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candles_backup AS SELECT * FROM candles;
CREATE TABLE IF NOT EXISTS derivatives_backup AS SELECT * FROM derivatives;
CREATE TABLE IF NOT EXISTS snapshots_backup AS SELECT * FROM snapshots;
CREATE TABLE IF NOT EXISTS flows_backup AS SELECT * FROM flows;
CREATE TABLE IF NOT EXISTS decisions_backup AS SELECT * FROM decisions;
CREATE TABLE IF NOT EXISTS equity_curve_backup AS SELECT * FROM equity_curve;
CREATE TABLE IF NOT EXISTS logs_backup AS SELECT * FROM logs;
CREATE TABLE IF NOT EXISTS orders_backup AS SELECT * FROM orders;
CREATE TABLE IF NOT EXISTS trades_backup AS SELECT * FROM trades;
CREATE TABLE IF NOT EXISTS executions_backup AS SELECT * FROM executions;
CREATE TABLE IF NOT EXISTS bot_state_backup AS SELECT * FROM bot_state;
CREATE TABLE IF NOT EXISTS positions_backup AS SELECT * FROM positions;
CREATE TABLE IF NOT EXISTS notifications_backup AS SELECT * FROM notifications;
CREATE TABLE IF NOT EXISTS etp_flows_backup AS SELECT * FROM etp_flows;
CREATE TABLE IF NOT EXISTS liquidation_zones_history_backup AS SELECT * FROM liquidation_zones_history;
CREATE TABLE IF NOT EXISTS news_sentiment_history_backup AS SELECT * FROM news_sentiment_history;

-- ------------------------------------------------------------
-- 2) candles: приведение BIGINT(ms) -> DATETIME и переименование OHLC
-- ------------------------------------------------------------
RENAME TABLE candles TO candles_legacy;

CREATE TABLE candles (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol       VARCHAR(20)     NOT NULL,
    timeframe    VARCHAR(10)     NOT NULL,
    open_time    DATETIME        NOT NULL,
    close_time   DATETIME        NOT NULL,
    open_price   DECIMAL(20, 8)  NOT NULL,
    high_price   DECIMAL(20, 8)  NOT NULL,
    low_price    DECIMAL(20, 8)  NOT NULL,
    close_price  DECIMAL(20, 8)  NOT NULL,
    volume       DECIMAL(28, 12) NOT NULL,
    quote_volume DECIMAL(28, 12) NULL,
    trades_count BIGINT          NULL,
    UNIQUE KEY uq_candles_symbol_tf_open (symbol, timeframe, open_time),
    KEY idx_candles_symbol_time (symbol, open_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO candles (
    id, symbol, timeframe, open_time, close_time,
    open_price, high_price, low_price, close_price,
    volume, quote_volume, trades_count
)
SELECT
    id,
    symbol,
    timeframe,
    FROM_UNIXTIME(open_time/1000),
    FROM_UNIXTIME(close_time/1000),
    open AS open_price,
    high AS high_price,
    low AS low_price,
    close AS close_price,
    volume,
    NULL AS quote_volume,
    NULL AS trades_count
FROM candles_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 3) derivatives: timestamp_ms -> DATETIME timestamp + новые метрики
-- ------------------------------------------------------------
RENAME TABLE derivatives TO derivatives_legacy;

CREATE TABLE derivatives (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol           VARCHAR(20)     NOT NULL,
    timestamp        DATETIME        NOT NULL,
    open_interest    DECIMAL(28, 12) NULL,
    funding_rate     DECIMAL(20, 10) NULL,
    taker_buy_volume DECIMAL(28, 12) NULL,
    taker_sell_volume DECIMAL(28, 12) NULL,
    taker_buy_ratio  DECIMAL(20, 10) NULL,
    basis            DECIMAL(20, 10) NULL,
    basis_pct        DECIMAL(10, 8)  NULL,
    cvd_1h           DECIMAL(20, 8)  NULL,
    cvd_4h           DECIMAL(20, 8)  NULL,
    extra_json       JSON            NULL,
    UNIQUE KEY uq_derivatives_symbol_ts (symbol, timestamp),
    KEY idx_derivatives_symbol_ts (symbol, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO derivatives (
    id, symbol, timestamp, open_interest, funding_rate,
    taker_buy_volume, taker_sell_volume, taker_buy_ratio,
    basis, basis_pct, cvd_1h, cvd_4h, extra_json
)
SELECT
    id,
    symbol,
    FROM_UNIXTIME(timestamp_ms/1000) AS timestamp,
    open_interest,
    funding_rate,
    taker_buy_volume,
    taker_sell_volume,
    taker_buy_ratio,
    NULL AS basis,
    NULL AS basis_pct,
    NULL AS cvd_1h,
    NULL AS cvd_4h,
    NULL AS extra_json
FROM derivatives_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 4) snapshots: соответствие целевой схеме
-- ------------------------------------------------------------
RENAME TABLE snapshots TO snapshots_legacy;

CREATE TABLE snapshots (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    captured_at_utc DATETIME        NOT NULL,
    price           DECIMAL(20, 8)  NOT NULL,
    timeframe       VARCHAR(16)     NOT NULL,
    structure_tag   VARCHAR(32)     DEFAULT NULL,
    momentum_tag    VARCHAR(32)     DEFAULT NULL,
    atr_5m          DECIMAL(20, 8)  DEFAULT NULL,
    session         VARCHAR(16)     DEFAULT NULL,
    payload_json    LONGTEXT        NOT NULL,
    UNIQUE KEY uq_snapshots_symbol_ts (symbol, captured_at_utc),
    KEY idx_snapshots_symbol_ts (symbol, captured_at_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO snapshots (
    id, symbol, captured_at_utc, price, timeframe,
    structure_tag, momentum_tag, atr_5m, session, payload_json
)
SELECT
    id,
    symbol,
    captured_at_utc,
    price,
    timeframe,
    structure_tag,
    momentum_tag,
    atr_5m,
    session,
    payload_json
FROM snapshots_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 5) flows: приведение к контракту
-- ------------------------------------------------------------
RENAME TABLE flows TO flows_legacy;

CREATE TABLE flows (
    id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)    NOT NULL,
    captured_at_utc    DATETIME       NOT NULL,
    current_price      DECIMAL(20, 8) NOT NULL,
    etp_net_flow_usd   DECIMAL(20, 2) DEFAULT NULL,
    crowd_bias_score   DECIMAL(10, 4) DEFAULT NULL,
    trap_index_score   DECIMAL(10, 4) DEFAULT NULL,
    risk_global_score  DECIMAL(10, 4) DEFAULT NULL,
    warnings_json      LONGTEXT       DEFAULT NULL,
    liquidation_json   LONGTEXT       DEFAULT NULL,
    etp_summary_json   LONGTEXT       DEFAULT NULL,
    payload_json       LONGTEXT       NOT NULL,
    UNIQUE KEY uq_flows_symbol_ts (symbol, captured_at_utc),
    KEY idx_flows_symbol_ts (symbol, captured_at_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO flows (
    id, symbol, captured_at_utc, current_price,
    etp_net_flow_usd, crowd_bias_score, trap_index_score, risk_global_score,
    warnings_json, liquidation_json, etp_summary_json, payload_json
)
SELECT
    id,
    symbol,
    captured_at_utc,
    current_price,
    etp_net_flow_usd,
    crowd_bias_score,
    trap_index_score,
    risk_global_score,
    warnings_json,
    liquidation_json,
    etp_summary_json,
    payload_json
FROM flows_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 6) decisions: преобразование колонок согласно документации
-- WARNING: возможны дубликаты по (symbol, timestamp); проверьте перед добавлением UNIQUE.
-- ------------------------------------------------------------
RENAME TABLE decisions TO decisions_legacy;

CREATE TABLE decisions (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol            VARCHAR(20)    NOT NULL,
    timestamp         DATETIME       NOT NULL,
    action            VARCHAR(16)    NOT NULL,
    reason            VARCHAR(255)   NULL,
    entry_min_price   DECIMAL(20, 8) NULL,
    entry_max_price   DECIMAL(20, 8) NULL,
    sl_price          DECIMAL(20, 8) NULL,
    tp1_price         DECIMAL(20, 8) NULL,
    tp2_price         DECIMAL(20, 8) NULL,
    risk_level        INT            NOT NULL DEFAULT 0,
    confidence        DECIMAL(10, 8) NOT NULL DEFAULT 0,
    position_size_usdt DECIMAL(20, 8) NOT NULL DEFAULT 0,
    leverage          DECIMAL(10, 4) NOT NULL DEFAULT 0,
    risk_checks_json  JSON           NULL,
    snapshot_id       BIGINT UNSIGNED NULL,
    flow_id           BIGINT UNSIGNED NULL,
    created_at        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_decisions_symbol_ts (symbol, timestamp),
    KEY idx_decisions_ts (timestamp),
    KEY idx_decisions_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO decisions (
    id, symbol, timestamp, action, reason,
    entry_min_price, entry_max_price, sl_price, tp1_price, tp2_price,
    risk_level, confidence, position_size_usdt, leverage,
    risk_checks_json, snapshot_id, flow_id, created_at
)
SELECT
    id,
    symbol,
    timestamp,
    action,
    rationale AS reason,
    price_ref AS entry_min_price,
    price_ref AS entry_max_price,
    stop_loss AS sl_price,
    take_profit AS tp1_price,
    NULL AS tp2_price,
    0 AS risk_level,
    confidence,
    position_size AS position_size_usdt,
    0 AS leverage,
    risk_flags AS risk_checks_json,
    snapshot_ref AS snapshot_id,
    flow_ref AS flow_id,
    COALESCE(created_at, NOW()) AS created_at
FROM decisions_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 7) equity_curve: типы и индексы
-- ------------------------------------------------------------
ALTER TABLE equity_curve_backup RENAME TO equity_curve_legacy;

CREATE TABLE equity_curve (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    timestamp      DATETIME       NOT NULL,
    equity_usdt    DECIMAL(20, 8) NOT NULL,
    balance_usdt   DECIMAL(20, 8) NULL,
    unrealized_pnl DECIMAL(20, 8) NULL,
    realized_pnl   DECIMAL(20, 8) NULL,
    daily_pnl      DECIMAL(20, 8) NULL,
    weekly_pnl     DECIMAL(20, 8) NULL,
    UNIQUE KEY uq_equity_ts (timestamp),
    KEY idx_equity_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO equity_curve (
    id, timestamp, equity_usdt, balance_usdt, unrealized_pnl, realized_pnl, daily_pnl, weekly_pnl
)
SELECT id, timestamp, equity_usdt, balance_usdt, unrealized_pnl, realized_pnl, daily_pnl, weekly_pnl
FROM equity_curve_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 8) logs: типы и индексы
-- ------------------------------------------------------------
ALTER TABLE logs_backup RENAME TO logs_legacy;

CREATE TABLE logs (
    id        BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME      NOT NULL,
    level     VARCHAR(16)   NOT NULL,
    source    VARCHAR(64)   NOT NULL,
    message   VARCHAR(1024) NOT NULL,
    context   JSON          NULL,
    KEY idx_logs_ts (timestamp),
    KEY idx_logs_level (level),
    KEY idx_logs_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO logs (id, timestamp, level, source, message, context)
SELECT id, timestamp, level, source, message, context
FROM logs_legacy
ORDER BY id;

-- ------------------------------------------------------------
-- 9) Создание отсутствующих таблиц по документации
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    timestamp        DATETIME        NOT NULL,
    level            VARCHAR(16)     NOT NULL,
    source           VARCHAR(64)     NOT NULL,
    code             VARCHAR(64)     NOT NULL,
    message          VARCHAR(1024)   NOT NULL,
    payload          JSON            NULL,
    delivery_status  VARCHAR(16)     NOT NULL DEFAULT 'pending',
    delivery_channel VARCHAR(64)     NULL,
    delivery_attempts INT            NOT NULL DEFAULT 0,
    last_attempt_at  DATETIME        NULL,
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_notifications_ts (timestamp),
    KEY idx_notifications_level (level),
    KEY idx_notifications_source (source),
    KEY idx_notifications_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS positions (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol           VARCHAR(20)     NOT NULL,
    side             ENUM('long','short') NOT NULL,
    open_time        DATETIME        NOT NULL,
    close_time       DATETIME        NULL,
    avg_entry_price  DECIMAL(20, 8)  NOT NULL,
    avg_exit_price   DECIMAL(20, 8)  NULL,
    qty              DECIMAL(20, 8)  NOT NULL,
    realized_pnl     DECIMAL(20, 8)  NULL,
    decision_open_id BIGINT UNSIGNED NULL,
    decision_close_id BIGINT UNSIGNED NULL,
    status           ENUM('OPEN','CLOSED') NOT NULL DEFAULT 'OPEN',
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_positions_symbol_status (symbol, status),
    KEY idx_positions_open_time (open_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS etp_flows (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol        VARCHAR(20)    NOT NULL,
    etp_date      DATE           NOT NULL,
    net_flow_usd  DECIMAL(20, 2) NOT NULL,
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_etp_flows_symbol_date (symbol, etp_date),
    KEY idx_etp_flows_date (etp_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS liquidation_zones_history (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol         VARCHAR(20)     NOT NULL,
    as_of          DATETIME        NOT NULL,
    current_price  DECIMAL(20, 8)  NOT NULL,
    side           ENUM('long', 'short') NOT NULL,
    position_rel   ENUM('above', 'below') NOT NULL,
    center_price   DECIMAL(20, 8)  NOT NULL,
    zone_min       DECIMAL(20, 8)  NOT NULL,
    zone_max       DECIMAL(20, 8)  NOT NULL,
    strength       DECIMAL(10, 8)  NOT NULL,
    comment        VARCHAR(255)    NULL,
    KEY idx_liq_symbol_asof (symbol, as_of),
    KEY idx_liq_symbol_side (symbol, side, as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS news_sentiment_history (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    as_of       DATETIME        NOT NULL,
    score       INT             NOT NULL,
    label       VARCHAR(20)     NOT NULL,
    comment     VARCHAR(512)    NULL,
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_sentiment_asof (as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------
-- 10) Ручная проверка и очистка
-- ------------------------------------------------------------
-- * Проверьте дубликаты по UNIQUE-ключам перед активацией (candles/snapshots/flows/decisions).
-- * После валидации можно дропнуть *_legacy таблицы.
-- * Сверьте внешние ключи, если они описаны в DATABASE_SCHEMA.md (не добавлены здесь, чтобы не блокировать миграцию при грязных данных).
