# AI Trading Showdown Bot – Database Schema (MariaDB)

Version: 1.0  
Status: Designed to match ARCHITECTURE, DATA_PIPELINE, DECISION_ENGINE, EXECUTION_ENGINE and RISK_MANAGER specs.

---

## 1. Purpose

This document defines the **relational schema** for the AI Trading Showdown Bot using **MariaDB** as the primary data store.

Goals:

- store all **historical data** required for:
  - live analytics,
  - decision-making,
  - execution and reconciliation,
  - performance & risk analysis,
  - backtesting;
- keep data **normalized** where it matters and **denormalized** where it accelerates analytics;
- use correct **numeric types** (DECIMAL) for money and prices;
- ensure proper **indexing** for time-series queries.

JSON files (`btc_snapshot.json`, `btc_flow.json`, etc.) are only last-state snapshots.  
**MariaDB is the source of truth** for all historical data.

---

## 2. General Design Principles

1. **Time in UTC**
   - All timestamps stored as `DATETIME` or `TIMESTAMP` in UTC.
   - Application layer is responsible for local timezone conversions.

2. **Numeric Precision**
   - Prices and quantities → `DECIMAL(20, 8)`.
   - Funding, percentages → `DECIMAL(10, 8)` or similar.
   - Equity/PnL → `DECIMAL(20, 8)`.

3. **Primary Keys**
   - Synthetic integer PKs (`BIGINT UNSIGNED AUTO_INCREMENT`) for most tables.
   - Composite keys where natural (e.g. `symbol + timeframe + open_time`).

4. **Indexes**
   - Every time-series table indexed by:
     - `symbol` + `time` (often composite).
   - Additional indexes for:
     - `decision_id`, `order_id`, `position_id`,
     - severity in logs.

5. **Retention**
   - 1m candles: 6–12 months minimum.
   - Other data: 1–2 years or more, depending on disk.

---

## 3. Time-Series Market Data

### 3.1 `candles` – OHLCV Data

Stores market candles for BTCUSDT (and optionally other symbols).

```sql
CREATE TABLE candles (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol       VARCHAR(20)     NOT NULL,   -- e.g. 'BTCUSDT'
    timeframe    VARCHAR(10)     NOT NULL,   -- '1m', '5m', '15m', '1h', '4h', '1d'

    open_time    DATETIME        NOT NULL,   -- candle open time (UTC)
    close_time   DATETIME        NOT NULL,   -- candle close time (UTC)

    open_price   DECIMAL(20, 8)  NOT NULL,
    high_price   DECIMAL(20, 8)  NOT NULL,
    low_price    DECIMAL(20, 8)  NOT NULL,
    close_price  DECIMAL(20, 8)  NOT NULL,

    volume       DECIMAL(28, 12) NOT NULL,   -- base volume
    quote_volume DECIMAL(28, 12) NULL,       -- quote volume (optional)

    trades_count BIGINT          NULL,

    UNIQUE KEY uq_candles_symbol_tf_open (symbol, timeframe, open_time),
    KEY idx_candles_symbol_time (symbol, open_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 3.2 `derivatives` – OI, Funding, CVD, Basis

Stores key derivatives metrics by time.

```sql
CREATE TABLE derivatives (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,   -- 'BTCUSDT'
    timestamp       DATETIME        NOT NULL,   -- UTC

    open_interest   DECIMAL(20, 8)  NULL,
    funding_rate    DECIMAL(10, 8)  NULL,
    funding_interval VARCHAR(10)    NULL,      -- e.g. '8h'

    basis           DECIMAL(20, 8)  NULL,      -- optional
    basis_pct       DECIMAL(10, 8)  NULL,

    cvd_1h          DECIMAL(20, 8)  NULL,
    cvd_4h          DECIMAL(20, 8)  NULL,

    extra_json      JSON            NULL,

    UNIQUE KEY uq_derivatives_symbol_ts (symbol, timestamp),
    KEY idx_derivatives_symbol_ts (symbol, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 4. ETF Flows, Liquidation Zones, Sentiment

### 4.1 `etp_flows` – Daily ETF Flows

Represents per-day net flows, as in `btc_etp_flow.json.history`.

```sql
CREATE TABLE etp_flows (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol        VARCHAR(20)    NOT NULL,       -- 'BTC'
    etp_date      DATE           NOT NULL,       -- YYYY-MM-DD
    net_flow_usd  DECIMAL(20, 2) NOT NULL,       -- net daily flow in USD

    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_etp_flows_symbol_date (symbol, etp_date),
    KEY idx_etp_flows_date (etp_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Optional aggregated/summarised table (for caching last 3/7 days) is not strictly required if application computes it on the fly.

---

### 4.2 `liquidation_zones_history` – Liq Map Snapshots

Stores every snapshot of liquidation clusters.

```sql
CREATE TABLE liquidation_zones_history (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol         VARCHAR(20)     NOT NULL,        -- 'BTC'
    as_of          DATETIME        NOT NULL,        -- snapshot time, UTC

    current_price  DECIMAL(20, 8)  NOT NULL,

    side           ENUM('long', 'short') NOT NULL,  -- which side's liqs
    position_rel   ENUM('above', 'below') NOT NULL, -- relative to current price

    center_price   DECIMAL(20, 8)  NOT NULL,
    zone_min       DECIMAL(20, 8)  NOT NULL,
    zone_max       DECIMAL(20, 8)  NOT NULL,
    strength       DECIMAL(10, 8)  NOT NULL,        -- normalized 0..1

    comment        VARCHAR(255)    NULL,

    KEY idx_liq_symbol_asof (symbol, as_of),
    KEY idx_liq_symbol_side (symbol, side, as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Each row represents one zone (either above or below).  
This schema mirrors `btc_liquidation_map.json` while preserving history.

---

### 4.3 `news_sentiment_history` – Manual Sentiment

```sql
CREATE TABLE news_sentiment_history (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    as_of       DATETIME        NOT NULL,
    score       INT             NOT NULL,         -- typical range -2..+2
    label       VARCHAR(20)     NOT NULL,         -- 'bearish' / 'neutral' / 'bullish'
    comment     VARCHAR(512)    NULL,

    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_sentiment_asof (as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Latest row is used for current `news_sentiment.json`.

---

## 5. Analytics Snapshots & Flow

### 5.1 `snapshots` – btc_snapshot History

Stores all structural market snapshots.

```sql
CREATE TABLE snapshots (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,      -- 'BTCUSDT'
    timestamp       DATETIME        NOT NULL,      -- snapshot timestamp (UTC)

    price           DECIMAL(20, 8)  NOT NULL,

    -- optional key OHLC for quick access (e.g. last 5m candle)
    o_5m            DECIMAL(20, 8)  NULL,
    h_5m            DECIMAL(20, 8)  NULL,
    l_5m            DECIMAL(20, 8)  NULL,
    c_5m            DECIMAL(20, 8)  NULL,

    -- JSON blobs for more detailed structure
    candles_json        JSON        NULL,
    market_structure_json JSON      NULL,
    momentum_json       JSON        NULL,
    session_json        JSON        NULL,

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_snapshots_symbol_ts (symbol, timestamp),
    KEY idx_snapshots_ts (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

The JSON columns mirror `btc_snapshot.json` fields for full fidelity.

---

### 5.2 `flows` – btc_flow History

Stores aggregated flow context matching `btc_flow.json`.

```sql
CREATE TABLE flows (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,     -- 'BTCUSDT'
    timestamp       DATETIME        NOT NULL,

    derivatives_json   JSON         NULL,
    etp_summary_json   JSON         NULL,
    liquidation_json   JSON         NULL,
    crowd_json         JSON         NULL,
    trap_index_json    JSON         NULL,
    news_sentiment_json JSON        NULL,
    warnings_json      JSON         NULL,

    risk_global_score  DECIMAL(10, 8) NULL,
    risk_mode          VARCHAR(32)    NULL,      -- 'risk_off'/...

    created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_flows_symbol_ts (symbol, timestamp),
    KEY idx_flows_ts (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 6. Decisions & Trades

### 6.1 `decisions` – Decision History

Each row corresponds to one 5-minute decision produced by Decision Engine.

```sql
CREATE TABLE decisions (
    id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)     NOT NULL,     -- 'BTCUSDT'
    timestamp          DATETIME        NOT NULL,     -- same as snapshot/flow timestamp

    action             ENUM('long', 'short', 'flat') NOT NULL,
    reason             VARCHAR(255)    NOT NULL,

    entry_min_price    DECIMAL(20, 8)  NULL,
    entry_max_price    DECIMAL(20, 8)  NULL,
    sl_price           DECIMAL(20, 8)  NULL,
    tp1_price          DECIMAL(20, 8)  NULL,
    tp2_price          DECIMAL(20, 8)  NULL,

    risk_level         INT             NOT NULL DEFAULT 0,   -- 0..5
    position_size_usdt DECIMAL(20, 8)  NOT NULL DEFAULT 0,
    leverage           DECIMAL(10, 4)  NOT NULL DEFAULT 0,

    confidence         DECIMAL(10, 8)  NOT NULL DEFAULT 0,

    risk_checks_json   JSON            NULL,   -- daily_dd_ok, etc.

    snapshot_id        BIGINT UNSIGNED NULL,   -- FK to snapshots.id
    flow_id            BIGINT UNSIGNED NULL,   -- FK to flows.id

    created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_decisions_symbol_ts (symbol, timestamp),
    KEY idx_decisions_ts (timestamp),
    KEY idx_decisions_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Foreign keys can be enforced at DB level or handled at application level.

---

### 6.2 `orders` – Orders Sent to Binance

This table logs **all** orders (entry, SL, TP, partials).

```sql
CREATE TABLE orders (
    id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    binance_order_id   BIGINT         NULL,        -- Binance's orderId
    client_order_id    VARCHAR(64)    NOT NULL,    -- newClientOrderId (idempotent key)

    symbol             VARCHAR(20)    NOT NULL,    -- 'BTCUSDT'
    side               ENUM('BUY', 'SELL') NOT NULL,
    type               VARCHAR(32)    NOT NULL,    -- LIMIT / MARKET / STOP / TAKE_PROFIT / ...
    time_in_force      VARCHAR(8)     NULL,        -- GTC / IOC / FOK

    decision_id        BIGINT UNSIGNED NULL,       -- link to decisions.id
    position_id        BIGINT UNSIGNED NULL,       -- optional future extension

    status             VARCHAR(32)    NOT NULL,    -- NEW / PARTIALLY_FILLED / FILLED / CANCELED / ...
    created_at_exchange DATETIME      NULL,        -- Binance's transactTime
    updated_at_exchange DATETIME      NULL,

    price              DECIMAL(20, 8) NOT NULL,
    orig_qty           DECIMAL(20, 8) NOT NULL,
    executed_qty       DECIMAL(20, 8) NOT NULL DEFAULT 0,
    cumulative_quote   DECIMAL(20, 8) NOT NULL DEFAULT 0,

    is_entry           TINYINT(1)     NOT NULL DEFAULT 0,
    is_sl              TINYINT(1)     NOT NULL DEFAULT 0,
    is_tp              TINYINT(1)     NOT NULL DEFAULT 0,

    created_at         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_orders_client_order (client_order_id),
    KEY idx_orders_decision (decision_id),
    KEY idx_orders_symbol_status (symbol, status),
    KEY idx_orders_exchange_order (binance_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 6.3 `trades` – Executed Fills

Some systems prefer to track executed trades separately from orders; this is recommended here.

```sql
CREATE TABLE trades (
    id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    order_id           BIGINT UNSIGNED NOT NULL,       -- FK to orders.id
    binance_trade_id   BIGINT          NULL,           -- tradeId from Binance

    symbol             VARCHAR(20)     NOT NULL,
    side               ENUM('BUY', 'SELL') NOT NULL,

    price              DECIMAL(20, 8)  NOT NULL,
    qty                DECIMAL(20, 8)  NOT NULL,
    quote_qty          DECIMAL(20, 8)  NOT NULL,

    commission         DECIMAL(20, 8)  NULL,
    commission_asset   VARCHAR(16)     NULL,

    realized_pnl       DECIMAL(20, 8)  NULL,          -- if provided by API or computed

    exec_time          DATETIME        NOT NULL,      -- transactTime converted to DATETIME UTC

    created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_trades_order (order_id),
    KEY idx_trades_symbol_time (symbol, exec_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 7. Equity Curve & Performance

### 7.1 `equity_curve` – Equity Over Time

Stores equity snapshots (e.g. every 5 minutes, or on trade events).

```sql
CREATE TABLE equity_curve (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    timestamp      DATETIME        NOT NULL,
    symbol         VARCHAR(20)     NOT NULL DEFAULT 'BTCUSDT',

    equity_usdt    DECIMAL(20, 8)  NOT NULL,
    balance_usdt   DECIMAL(20, 8)  NULL,        -- wallet balance
    unrealized_pnl DECIMAL(20, 8)  NULL,
    realized_pnl   DECIMAL(20, 8)  NULL,

    daily_pnl      DECIMAL(20, 8)  NULL,
    weekly_pnl     DECIMAL(20, 8)  NULL,

    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_equity_ts (timestamp),
    KEY idx_equity_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

This table is used for:

- DD calculation,
- performance analytics,
- backtest vs live comparison.

---

## 8. Logging & Diagnostics

### 8.1 `logs` – Structured Log Entries

The system writes important events to DB (in addition to file logs).

```sql
CREATE TABLE logs (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    timestamp   DATETIME        NOT NULL,
    level       VARCHAR(16)     NOT NULL,    -- 'INFO' / 'WARNING' / 'ERROR' / 'CRITICAL'
    source      VARCHAR(64)     NOT NULL,    -- 'analytics', 'decision', 'execution', 'dashboard', 'system'
    message     VARCHAR(1024)   NOT NULL,
    context     JSON            NULL,        -- additional fields (order_id, decision_id, etc.)

    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_logs_ts (timestamp),
    KEY idx_logs_level (level),
    KEY idx_logs_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---


### 8.2 `notifications` – Alerts & Notifications

Все уведомления, отправляемые Notifier'ом (и те, что не удалось отправить), хранятся здесь.

```sql
CREATE TABLE notifications (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    timestamp     DATETIME        NOT NULL,
    level         VARCHAR(16)     NOT NULL,    -- INFO / WARNING / ERROR / CRITICAL
    source        VARCHAR(64)     NOT NULL,    -- 'execution', 'risk', 'reconciliation', 'analytics', 'system'
    code          VARCHAR(64)     NOT NULL,    -- 'MISSING_SL', 'DAILY_DD_BREACH', 'ETF_STALE', ...

    message       VARCHAR(1024)   NOT NULL,    -- краткий читаемый текст
    payload       JSON            NULL,        -- подробный контекст (symbol, decision_id, order_id, price, etc.)

    delivery_status VARCHAR(16)   NOT NULL DEFAULT 'pending',  -- 'pending' / 'sent' / 'failed'
    delivery_channel VARCHAR(64)  NULL,        -- e.g. 'telegram'
    delivery_attempts INT         NOT NULL DEFAULT 0,
    last_attempt_at DATETIME      NULL,

    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_notifications_ts (timestamp),
    KEY idx_notifications_level (level),
    KEY idx_notifications_source (source),
    KEY idx_notifications_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Эта таблица используется:
- Dashboard'ом (раздел Alerts),
- для аудита и отладки,
- для анализа стабильности системы.


## 9. Optional Tables

These are not strictly required but useful for clarity and extension.

### 9.1 `positions` – Logical Net Positions (optional)

Tracks the lifecycle of net positions for reporting and reconciliation.

```sql
CREATE TABLE positions (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    symbol          VARCHAR(20)     NOT NULL,
    side            ENUM('long', 'short') NOT NULL,

    open_time       DATETIME        NOT NULL,
    close_time      DATETIME        NULL,

    avg_entry_price DECIMAL(20, 8)  NOT NULL,
    avg_exit_price  DECIMAL(20, 8)  NULL,

    qty             DECIMAL(20, 8)  NOT NULL,
    realized_pnl    DECIMAL(20, 8)  NULL,

    decision_open_id BIGINT UNSIGNED NULL,   -- decisions.id that opened it
    decision_close_id BIGINT UNSIGNED NULL,  -- decisions.id that closed it

    status          ENUM('OPEN', 'CLOSED') NOT NULL DEFAULT 'OPEN',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_positions_symbol_status (symbol, status),
    KEY idx_positions_open_time (open_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 9.2 `reconciliation_events` – Reconciliation Logs (optional)

For each reconciliation run, store summary and details.

```sql
CREATE TABLE reconciliation_events (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    started_at       DATETIME        NOT NULL,
    finished_at      DATETIME        NULL,

    orphan_positions INT             NOT NULL DEFAULT 0,
    phantom_positions INT            NOT NULL DEFAULT 0,
    missing_sl       INT             NOT NULL DEFAULT 0,
    orphan_orders    INT             NOT NULL DEFAULT 0,

    summary          VARCHAR(1024)   NULL,
    details_json     JSON            NULL,

    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_recon_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 10. Relationships Summary

- `snapshots` ← time-series of `btc_snapshot`.
- `flows` ← time-series of `btc_flow`.
- `decisions`:
  - references `snapshots` and `flows` by timestamps and optional IDs.
  - linked to `orders` via `decision_id`.
- `orders`:
  - linked to `trades` via `order_id`.
- `trades`:
  - aggregated into `positions` (optional) and contribute to `equity_curve`.
- `equity_curve`:
  - used by Risk Manager to calculate DD and mode.
- `etp_flows`, `liquidation_zones_history`, `news_sentiment_history`:
  - provide historical context feeding into `flows`.

---

## 11. Migration and Evolution Strategy

The schema is designed to be:

- **extendable**:
  - new JSON fields can be added in `*_json` columns without migration.
- **compatible** with multiple symbols:
  - `symbol` present in all core tables.
- **backtest-friendly**:
  - backtesting engine can read from the same tables as live systems.

When adding new metrics:

- prefer adding them into a JSON column first;
- if they become critical for queries, materialize them into dedicated columns.

---

## 12. Summary

This schema provides a robust foundation for:

- real-time analytics,
- deterministic decision-making,
- safe execution and reconciliation,
- detailed performance and risk analytics,
- consistent backtesting.

It directly reflects the contracts described in:

- `ARCHITECTURE.md`
- `DATA_PIPELINE.md`
- `DECISION_ENGINE.md`
- `EXECUTION_ENGINE.md`
- `RISK_MANAGER.md`

and is tailored for a **production-grade MariaDB deployment** of the AI Trading Showdown Bot.
