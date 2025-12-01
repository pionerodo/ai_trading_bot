# AI Trading Showdown Bot – System Architecture

Version: 1.0  
Status: Draft (aligned with core Technical Specification)

---

## 1. Purpose and Scope

This document describes the **overall architecture** of the AI Trading Showdown Bot deployed on a dedicated Python stack under a subdomain such as `ai-hedge.cryptobavaro.online`.

The goal of the system is to provide an **autonomous BTCUSDT analytics and trading pipeline** that:

- Collects and stores market and derivatives data (primarily Binance Futures BTCUSDT PERP).
- Ingests *human-assisted* external context (ETF flows, liquidation maps, news/social sentiment) via JSON.
- Builds structured analytics snapshots and aggregated “flow” views of the market.
- Applies deterministic **Decision Engine** rules for trade decisions and risk management.
- Executes those decisions on Binance (testnet → mainnet) via a robust **Execution Engine**.
- Provides a web dashboard for manual inputs, monitoring, logs and diagnostics.
- Logs all actions and supports historical analysis and backtesting via MariaDB.

This document focuses on **modules, processes, data flows and deployment**, while low‑level details (JSON schemas, decision logic, DB schema, etc.) live in:

- `DATA_PIPELINE.md`
- `DECISION_ENGINE.md`
- `EXECUTION_ENGINE.md`
- `RISK_MANAGER.md`
- `DATABASE_SCHEMA.md`
- `BACKTESTING.md`

---

## 2. High‑Level Architecture Overview

At the highest level the system is a **pipeline of services** connected by the database and a small set of JSON snapshot files:

```text
        +------------------+
        |  External Input  |
        |  (User + LLM)    |
        |  ETF / Liq /     |
        |  Sentiment JSON  |
        +---------+--------+
                  |
                  v
+-----------------+-----------------------------+
|               Data Layer                      |
|  (Binance, MariaDB, JSON snapshots)          |
+-----------------+-----------------------------+
                  |
                  v
+-----------------+-----------------------------+
|               Analytics Engine                |
|  - btc_snapshot generator                     |
|  - btc_flow generator (incl. ETF/Liq/etc.)    |
+-----------------+-----------------------------+
                  |
                  v
+-----------------+-----------------------------+
|               Decision Engine                 |
|  - Rule-based trade logic                     |
|  - Risk manager                               |
|  - decision.json                              |
+-----------------+-----------------------------+
                  |
                  v
+-----------------+-----------------------------+
|               Execution Engine                |
|  - Execution Loop (1–3s)                      |
|  - Binance API / Orders / Positions           |
|  - Reconciliation on startup                  |
+-----------------+-----------------------------+
                  |
                  v
+-----------------+-----------------------------+
|                Dashboard & API                |
|  - Manual inputs (sentiment, JSON uploads)    |
|  - State & PnL monitoring                     |
|  - Logs, errors, risk status                  |
+------------------------------------------------
```

Core architectural principles:

1. **Separation of concerns**
   - Analytics, decisions, execution and UI are clearly separated into different modules.
2. **Separation of time scales**
   - **Analytics Loop** runs every 5 minutes.
   - **Execution Loop** runs continuously every 1–3 seconds.
3. **Database‑centric history**
   - All heavy historical data is stored in **MariaDB**.
   - JSON files are small, last‑state snapshots for interoperability and debugging.
4. **Rule‑based AI in v1**
   - No mandatory external LLM calls. Decisions are deterministic and explainable.
   - External LLM (e.g. ChatGPT) is used outside the system to help the operator prepare JSON inputs or analysis comments.
5. **Resilience and recovery**
   - Execution Engine performs **Reconciliation** on startup.
   - Risk limits and safety checks prevent uncontrolled trading.

---

## 3. Core Components

### 3.1 Data Collector Service

**Responsibility:** ingest live market data and derivatives, transform and store it.

Sub‑modules:

- **Candles Collector**
  - Fetches BTCUSDT Futures PERP candles from Binance:
    - Mandatory timeframes: `1m`, `5m`, `15m`, `1h`.
    - Optional: `4h`, `1d` for extended context.
  - Writes candles into MariaDB (`candles` table) with appropriate indices.
- **Derivatives Collector**
  - Collects derivatives data:
    - Open Interest (OI).
    - Funding rates (current and recent history).
    - Optional basis (spot vs perps).
    - Optional CVD approximations from trades.
  - Writes to `derivatives` table and/or related tables.
- **Optional TradingView/Webhooks**
  - The architecture allows adding a listener for TradingView webhooks to store additional indicator‑based signals in DB.
  - Not required for v1, but must be easy to attach later.

Output into other modules:

- DB rows in `candles`, `derivatives`.
- Latest data is used by Analytics Engine to build `btc_snapshot.json`.

Data Collector is **stateless** except for DB; it can be restarted without losing logic, as long as DB is intact.

---

### 3.2 Analytics Engine

**Responsibility:** transform raw data + external JSON context into structured views of the market.

It produces mainly two JSON views:

- `btc_snapshot.json` — structural view of the market “right now”.
- `btc_flow.json` — aggregated “flow” and crowd/risk view.

Modules:

1. **Snapshot Generator**
   - Reads recent candles from DB (multiple TFs).
   - Computes:
     - **Market structure** (HH/HL/LH/LL) using swing‑high/swing‑low detection.
     - **Momentum** per TF (impulse up/down, fading, choppy + scores).
     - **Volatility regime** using ATR on key TFs.
     - **Session** – Asia / Europe / US based on time and UTC.
   - Writes the current state to:
     - DB table `snapshots` (full detail).
     - Snapshot file `data/btc_snapshot.json` (latest only).

2. **Flow Generator**
   - Reads:
     - Latest derivatives from DB (`derivatives`).
     - Summarized ETF flows from `btc_etp_flow.json`.
     - Liquidation zones from `btc_liquidation_map.json`.
     - Manual sentiment from `news_sentiment.json`.
   - Computes:
     - **Derivatives context** (funding, OI change, CVD).
     - **Crowd bias**: which side is the crowd overleveraging.
     - **Trap index**: how much fuel there is to move against late entrants.
     - **Warnings**: extreme funding, extreme clustering of liqs, etc.
     - **Global risk score**: 0–1 scale that indicates how safe/aggressive trading should be.
   - Writes:
     - DB `flows` table — full history.
     - Snapshot `data/btc_flow.json` — last state.

Analytics Engine is **triggered every 5 minutes** (cron/scheduler). It does *not* execute trades.

---

### 3.3 Decision Engine

**Responsibility:** given `btc_snapshot` + `btc_flow` + current account state, decide whether to:

- go **long**,  
- go **short**, or  
- stay **flat**,

and compute a full **decision object** (`decision.json`) including risk and position sizing.

Key ideas:

- **Rule‑based logic** in v1:
  - Long/short conditions based on structure, momentum, derivatives, ETF, liqs and sentiment.
  - Flat if signals conflict or risk is too high.
- **Integrated risk manager**:
  - Daily and weekly DD limits.
  - Max trades per day / conflict filters.
  - Session filters (e.g. avoid low‑liquidity zones).
  - ATR‑based SL/TP and position sizing:
    - Risk per trade = equity * risk_percent.
    - Position size scaled by distance to SL and volatility.
- **Outputs**:
  - `decision.json` snapshot.
  - DB `decisions` table (full history).

The Decision Engine is logically part of **Analytics Loop** (same 5‑minute cadence), but **Execution Loop** consumes its decisions at a higher frequency.

Details of rules and risk logic are fully specified in `DECISION_ENGINE.md` and `RISK_MANAGER.md`.

---

### 3.4 Execution Engine

**Responsibility:** transform **decisions** into **real orders and positions** on Binance and maintain them safely over time.

It consists of two main parts:

1. **Execution Loop (1–3s cadence)**
   - Runs continuously in a `while True` loop with a small sleep (1–3 seconds).
   - Responsibilities:
     - Fetch current market price (via WebSocket or REST).
     - Read latest **approved decision** from DB or cache.
     - Manage entry orders:
       - Place initial limit orders in the decision’s entry zone.
       - Apply “chase” logic: if price moves away within allowed bounds, adjust or cancel.
       - Optionally perform fail‑safe market entry when conditions permit (high confidence, small slippage).
     - Manage SL/TP orders:
       - Ensure SL and TP(s) exist for each open position.
       - Move or re‑place SL/TP based on trailing or partial TP logic (v1 minimal, v1.1 can extend).
     - Ensure idempotent behaviour:
       - Use unique `newClientOrderId` values to avoid duplicate orders on retries.
       - De‑duplicate events if network/API retries occur.

2. **Reconciliation and Recovery**
   - Executes on service **startup or restart**:
     - Query Binance:
       - Open positions (`positionRisk`).
       - Open orders.
     - Compare with DB:
       - If Binance has a position that DB doesn’t know about → **Emergency Import**: create position record and log a WARNING.
       - If DB has an “open” position but Binance doesn’t → mark it closed based on last known SL/TP or emergency close, log WARNING.
       - If there is a position but no SL/TP orders → immediately create SL (and basic TP) to protect the account.
   - Logs all mismatches and sends notifications via Telegram.
   - After reconciliation, Execution Loop continues in steady state.

Execution Engine **must not** do analytics or complex decisions; it trusts the latest `decision` but retains the right to **refuse execution** if local risk checks fail (e.g. equity mismatch, connection issues).

Full behavioural details are in `EXECUTION_ENGINE.md`.

---

### 3.5 Dashboard / Web UI

**Responsibility:** provide a human‑friendly control and monitoring layer.

Main features:

1. **Status and Overview**
   - Current BTC price and basic market regime.
   - Bot status: RUNNING / PAUSED / ERROR.
   - Current position: side, size, entry, SL/TP, unrealized PnL.
   - Equity and PnL:
     - Day / week / total.

2. **Manual Inputs**
   - Form for **manual sentiment**:
     - Score (e.g. -2…+2 or bearish/neutral/bullish).
     - Comment (short text).
     - Writes into `news_sentiment.json` + DB.
   - JSON upload / paste for:
     - `btc_etp_flow.json` (ETF flows derived from LLM based on screenshots).
     - `btc_liquidation_map.json` (liquidation zones derived from LLM based on screenshots).
   - Validation of JSON format and clear error reporting.

3. **History and Analytics**
   - Trade history: orders and aggregated trades.
   - High‑level metrics: win rate, avg R/R, DDs.
   - Links into backtesting reports (if implemented).

4. **Logs and Diagnostics**
   - Recent log entries (tail of `logs/bot.log` or DB `logs`).
   - Filters by severity (INFO/WARNING/ERROR).
   - Highlight of latest ERROR and risk events.

5. **Control Panel (optional)**
   - Buttons to pause/resume execution.
   - Toggles for modes (“simulation/live”, “testnet/mainnet”) – ideally behind strong auth.

Technical stack (recommended, but not rigidly fixed):

- Backend: FastAPI or Flask.
- Frontend:
  - either lightweight templating (Jinja2 + HTMX),
  - or a small SPA (React/Vue) for richer UX.
- Authentication: at least basic username/password with hashed credentials.

---

### 3.6 Logging and Notifications

Logging is a **first‑class architecture concern**.

- **Log destinations**:
  - Text file(s): under `logs/`, using rotating handlers.
  - DB `logs` table: for filtered and structured events.
- **Log contents**:
  - Startup/shutdown of components.
  - Each analytics cycle (timestamp, success, key stats).
  - Each decision (compressed summary).
  - All order placement/cancellation/fill events.
  - Errors and exceptions with stack traces and context.
- **Notification system**:
  - Telegram bot for critical events:
    - ERRORs (exceptions, API failures).
    - Hitting daily/weekly DD limits (trading stopped).
    - Reconciliation anomalies (orphan positions, missing SL).
    - New position opened and position fully closed (optional compressed messages).

The notifier is a separate, small module subscribed to important events in Execution and Decision Engines.

---

## 4. Runtime Flows

### 4.1 Analytics Loop (5‑minute cadence)

Triggered by a scheduler (cron, APScheduler, or simple loop + sleep):

1. Collect recent candles and derivatives from DB.
2. Generate **btc_snapshot**:
   - Structure, momentum, ATR‑based volatility, session.
3. Load latest external JSON:
   - ETF flows (`btc_etp_flow.json`).
   - Liquidation map (`btc_liquidation_map.json`).
   - Manual sentiment (`news_sentiment.json`).
4. Generate **btc_flow**:
   - Derivatives context, crowd, traps, warnings, risk score.
5. Run **Decision Engine**:
   - Evaluate long/short/flat options.
   - Check risk manager constraints (DD, trades per day, session, etc.).
   - Produce **decision** (or FLAT).
6. Persist:
   - Insert into `snapshots`, `flows`, `decisions`.
   - Overwrite JSON snapshots (`btc_snapshot.json`, `btc_flow.json`, `decision.json`).
7. Log:
   - Summary of cycle and final decision.

Analytics Loop **does not wait for order fills**. It sets the strategic context; Execution Engine manages micro‑timing.

---

### 4.2 Execution Loop (1–3s cadence)

Runs as a long‑lived process:

1. Fetch latest `decision` (or use cached in‑memory).
2. Fetch current market and position state (price, open orders, position).
3. If decision is FLAT:
   - Optionally close residual positions (if allowed by logic).
   - Ensure no stale open orders exist.
4. If decision is LONG/SHORT:
   - Check if a position already exists:
     - If yes, ensure SL/TP are correct; possibly manage partial exits (v1 minimal).
     - If no, ensure entry orders exist and are within allowed distance to price.
   - Apply **chase logic** if price has moved moderately.
   - Cancel or upgrade to market order if:
     - decision has high confidence AND
     - price is still within safe distance.
5. Repeat with small delay (1–3s).

If Execution Loop detects a hard error (e.g. no API connectivity), it:

- logs an ERROR,
- sends a Telegram alert,
- optionally suspends trading until manual intervention.

---

### 4.3 Startup and Reconciliation Flow

On startup (or restart) of Execution Engine:

1. Load basic config (mode: testnet/mainnet, risk parameters).
2. Query Binance positions and open orders.
3. Read last known positions and decisions from DB.
4. Reconciliation:
   - Import missing positions.
   - Mark vanished positions as closed.
   - Restore SL/TP where absent.
5. Log the reconciliation summary and notify via Telegram if any mismatches were found.
6. Start main Execution Loop.

This design ensures that a restart or temporary outage does not leave the account unprotected.

---

## 5. Data and Storage Architecture

### 5.1 MariaDB as Source of Truth

Key architectural decision: **MariaDB stores all historical data**.

- Candles and derivatives are stored as granular time series.
- Each 5‑minute analytics cycle records:
  - a snapshot (`snapshots`),
  - a flow aggregation (`flows`),
  - a decision (`decisions`).
- Orders and trades are stored with relationships to decisions:
  - `orders` → `decisions` via `decision_id`.
  - `trades` → `orders` via `order_id`.
- `equity_curve` tracks the evolution of account equity (for live and backtest modes).
- `logs` track important events.

JSON files are **only** used as:

- latest‑state snapshots (very small),
- easy integration points for external tools or manual inspection.

Full details in `DATABASE_SCHEMA.md`.

---

### 5.2 History Retention

Minimum recommended retention:

- Candles 1m: 6–12 months.
- Higher TF candles and derivatives: 1–2 years.
- Decisions, trades, equity, sentiment, ETF, liquidation history: no set limit (can be archived if needed).

This allows robust after‑the‑fact analysis and backtesting.

---

## 6. Environments and Deployment

### 6.1 Environments

Two main runtime environments:

1. **Testnet**
   - Binance Futures Testnet API keys.
   - Same logic, but with small/simulated sizes.
   - Used to validate:
     - correctness of order workflows,
     - Reconciliation,
     - log and dashboard behaviour.
2. **Mainnet**
   - Production Binance Futures API keys.
   - Stricter risk limits.
   - Optional requirement: manual confirmation for first N trades.

Switching between modes is **configuration‑driven** via `config.yaml` / `config.local.yaml`.

---

### 6.2 Deployment Stack

Typical deployment:

- Host: Hetzner server managed via aaPanel.
- Web server: Nginx as reverse proxy.
- Application:
  - Python 3.10+ virtual environment.
  - Uvicorn/Gunicorn for dashboard API.
  - Separate processes (Supervisor/systemd):
    - Data Collector (candles + derivatives).
    - Analytics Loop (if implemented as long‑running process).
    - Execution Engine.
- Database: MariaDB (already in the hosting stack).
- Optional: Redis for caching or message passing between components.

Deployment layout (simplified):

```text
ai_trading_bot/
  config/
  data/
  logs/
  src/
    data_collector/
    analytics_engine/
    execution_engine/
    dashboard/
  docs/
  venv/
```

---

## 7. Security and Access

Key guidelines:

- API keys for Binance never stored in code; only in secure config (`.env` or `config.local.yaml` not committed to Git).
- Dashboard is **not public**:
  - At minimum: password‑protected for internal use.
  - Ideally behind VPN or IP whitelisting.
- Error logs must not contain secrets (API keys, passwords).
- Sensitive config files are in `.gitignore`.

---

## 8. Extensibility and Future Work

The architecture is designed to support future extensions without large rewrites:

- **Multi‑asset support (ETH, SOL, etc.)**
  - Data Collector: extend symbols.
  - Analytics Engine: multi‑symbol snapshots and flows.
  - Decision Engine: correlation‑aware risk manager.
  - DB: add `symbol` dimension everywhere (already assumed).
- **LLM Advisor Module**
  - Separate service (`llm_advisor`) that reads history from DB and produces:
    - Post‑trade analysis.
    - Strategy improvement suggestions.
  - No direct order control.
- **More advanced Execution logic**
  - Adaptive position scaling.
  - TWAP/VWAP‑style execution.
  - More nuanced partial exits.
- **Advanced Dashboard**
  - Charts for equity curves, DD, performance by regime.
  - Direct visualisations of ETF flows and liq zones.

---

## 9. Summary

The AI Trading Showdown Bot architecture:

- Separates analytics from execution and UI.
- Relies on MariaDB as the long‑term source of truth.
- Uses light JSON files for interoperability.
- Keeps trading logic deterministic and risk‑focused in v1.
- Provides clear extension points for:
  - additional assets,
  - deeper risk logic,
  - LLM‑based advisory,
  - richer front‑end.

This document should be used together with:

- `DATA_PIPELINE.md`
- `DECISION_ENGINE.md`
- `EXECUTION_ENGINE.md`
- `RISK_MANAGER.md`
- `DATABASE_SCHEMA.md`
- `BACKTESTING.md`

to get a complete understanding of the system.

---

# 12. LLM Advisory Module (Optional, Non‑Trading)

The LLM advisory layer is **not part of the trading pipeline** and has no ability to send orders,
modify decisions, or influence execution.  
Its purpose is strictly analytical:

### ✔ Data sources  
LLM works **only** with:
- historical data from MariaDB,
- snapshots & flows,
- trades & equity curve,
- risk metrics,
- backtest results.

### ✔ Responsibilities  
- создание текстовых аналитических отчётов;
- анализ статистики стратегий;
- сравнение версий (v1 vs v2);
- выявление аномалий в данных;
- интерпретация риск‑параметров и поведения бота.

### ✔ Restrictions  
- LLM **не может**:
  - отдавать торговые команды,
  - вмешиваться в Decision Engine,
  - модифицировать Execution Engine,
  - подменять risk‑checks.

### ✔ Purpose  
Это инструмент наблюдения и аналитики — «советник»,  
но не часть алгоритмического принятия решений.

---

## 13. Notification / Notifier Layer

Отдельный модуль **Notifier** отвечает за:

- приём событий от Execution Engine, Risk Manager, Reconciliation и Analytics;
- запись всех уведомлений в таблицу `notifications`;
- отправку важных событий в Telegram.

Notifier **не влияет** на торговые решения и не управляет ордерами — он только информирует.

