# AI Trading Showdown Bot – Backtesting Engine Specification

Version: 1.0  
Status: Fully aligned with ARCHITECTURE, DATA_PIPELINE, DECISION_ENGINE, EXECUTION_ENGINE, RISK_MANAGER, DATABASE_SCHEMA.

---

# 1. Purpose

The **Backtesting Engine** simulates the entire trading pipeline on **historical data** stored in MariaDB:

- candles  
- derivatives  
- ETF flows  
- liquidation zones  
- sentiment  
- snapshots  
- flows  
- decisions  
- trades  
- equity curve  

Backtesting ensures:

- strategy correctness,  
- robustness under different market regimes,  
- parameter tuning,  
- version comparison (model A vs model B),  
- regression testing after system updates.

Backtester uses **exact same logic** as live bot:

```
Historical Data → Snapshot → Flow → Decision → Simulated Execution → Results
```

No shortcuts, no simplified logic.

---

# 2. Backtesting Philosophy

### ✔ Accurate, not optimistic  
Backtester must not cheat by using future candles.

### ✔ Execution realism  
Simulates:

- limit orders  
- market orders  
- SL/TP  
- partial fills  
- slippage  
- spread  

### ✔ Modular  
Backtester does not modify live tables.  
It writes into dedicated *_backtest tables.

### ✔ Deterministic  
Given same inputs → identical results.

---

# 3. Inputs to Backtester

Backtesting Engine uses:

## 3.1 From DB

- `candles` (OHLCV per timeframe)
- `derivatives` (OI, funding, CVD, basis)
- `etp_flows`
- `liquidation_zones_history`
- `news_sentiment_history`

## 3.2 Configuration

- chosen symbol (default: BTCUSDT)
- timeframe for simulation (5 minutes)
- start_date / end_date
- execution mode:
  - `"ideal_limit_fill"` – optimistic (testing logic only)
  - `"market_in_reality"` – realistic slippage model
  - `"hybrid"` – limit fills if price crosses; otherwise slippage
- slippage settings
- commission model
- initial equity
- risk manager config

---

# 4. Backtesting Pipeline

Full process:

```
Load candles/derivatives → build synthetic snapshots → build flows →
run Decision Engine → simulate Execution Engine → save decisions/trades/equity →
repeat for each 5m step
```

Details below.

---

## 4.1 Step 1 — Load Historical Data

Backtester preloads:

- 1m / 5m / 15m / 1h candles
- derivative snapshots by timestamp
- ETF flows by date
- liquidation zones by timestamp
- sentiment data

Caching is used for speed.

---

## 4.2 Step 2 — Generate Snapshots (Historical)

Live bot generates snapshot every 5 minutes.  
Backtester reproduces the same:

For each simulation timestamp T:

1. Load latest candles before T.
2. Compute market structure:
   - HH/HL  
   - LL/LH  
3. Compute momentum:
   - impulse / fading / choppy  
   - score 0–1  
4. Compute ATR
5. Determine trading session (ASIA/EU/US)

Result → snapshot object identical to `btc_snapshot.json`.

This is written into:

```
snapshots_backtest
```

---

## 4.3 Step 3 — Generate Flow Aggregation

Flow Engine uses snapshot + external context.

At time T:

- derivatives data nearest to T  
- ETF flows (strict by day)  
- liquidation zones snapshot <= T  
- sentiment snapshot <= T  
- warnings  
- trap index  
- crowd bias  
- risk.global_score  

Result → flow object identical to `btc_flow.json`.

Written into:

```
flows_backtest
```

---

## 4.4 Step 4 — Decision Engine

Backtester calls the **same** Decision Engine code used in live trading.

Decision Engine returns:

- action: long/short/flat  
- entry zone  
- SL  
- TP1 / TP2  
- risk_level  
- position_size_usdt  
- leverage  
- confidence  
- risk_checks  

Written into:

```
decisions_backtest
```

---

# 5. Execution Simulation

This is the most critical part.

Backtester replicates Execution Engine logic as closely as possible.

---

## 5.1 Entry Simulation

### If action = FLAT  
→ no entries.

### If action = LONG/SHORT  
Backtester simulates:

1. Limit order at entry_mid.
2. If candle crosses entry zone:
   - entry fill occurs at:
     - exact limit price in optimistic mode, or
     - limit price + slippage in hybrid mode.
3. If candle does not cross entry zone:
   - no entry, unless confidence > threshold allowing market entry.
4. If market-entry allowed:
   - fill price = candle close ± slippage.

---

## 5.2 SL/TP Simulation

For each simulated 1m candle during trade:

Order of checks:

1. **SL check** (price crossing)  
2. **TP1 check**  
3. **TP2 check**

If SL and TP hit in same candle → SL priority.

Partial fills:

- TP1 closes 50% (configurable)  
- SL moves to breakeven if TP1 hit (optional)  
- TP2 closes remainder  

---

## 5.3 Fees

Per trade:

```
commission = executed_quote * fee_rate
```

Default Binance futures rate example:  
`0.0004` (taker), `0.0002` (maker).

---

## 5.4 Equity Update

After each trade:

```
equity = equity + realized_pnl - commission
```

Saved into:

```
equity_curve_backtest
```

Used to compute:

- daily/weekly DD  
- performance metrics  

---

# 6. Backtest Tables

## 6.1 `snapshots_backtest`

Identical structure to `snapshots`, but separate table.

## 6.2 `flows_backtest`

Identical to `flows`, but separate table.

## 6.3 `decisions_backtest`

Same as live `decisions`.

## 6.4 `trades_backtest`

Tracks simulated fills:

```sql
CREATE TABLE trades_backtest (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    decision_id    BIGINT UNSIGNED NOT NULL,
    symbol         VARCHAR(20)     NOT NULL,
    side           ENUM('BUY','SELL') NOT NULL,
    price          DECIMAL(20,8)   NOT NULL,
    qty            DECIMAL(20,8)   NOT NULL,
    realized_pnl   DECIMAL(20,8)   NULL,
    fee            DECIMAL(20,8)   NULL,
    action         ENUM('ENTRY','TP1','TP2','SL') NOT NULL,
    timestamp      DATETIME        NOT NULL,
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_trades_decision (decision_id),
    KEY idx_trades_time (timestamp)
);
```

---

## 6.5 `equity_curve_backtest`

Same as live, but separate table.

---

# 7. Performance Metrics Produced

Backtester computes:

### Core Metrics
- net profit  
- % return  
- max drawdown  
- max daily DD  
- Sharpe ratio  
- Sortino ratio  
- win rate  
- profit factor  
- avg R / median R  
- avg SL distance  
- avg TP distance  

### Distribution Metrics
- distribution of R-multiples  
- trade duration distribution  
- session performance (ASIA/EU/US)  
- performance by volatility regime  
- by ETF flow regimes  
- by crowd/trap regimes  

---

# 8. Strategy Versioning

Backtesting Engine must support:

```
strategy version A vs strategy version B
```

For each version:

- run complete backtest  
- store results in `backtest_runs` table  
- compare metrics

Example:

```sql
CREATE TABLE backtest_runs (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    version        VARCHAR(50) NOT NULL,
    start_date     DATE        NOT NULL,
    end_date       DATE        NOT NULL,
    initial_equity DECIMAL(20,8) NOT NULL,
    final_equity   DECIMAL(20,8) NOT NULL,
    max_dd         DECIMAL(10,5) NOT NULL,
    sharpe         DECIMAL(10,5) NULL,
    sortino        DECIMAL(10,5) NULL,
    win_rate       DECIMAL(10,5) NULL,
    notes          VARCHAR(512) NULL,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

# 9. Slippage Model

Backtester supports several modes:

### 9.1 Ideal (no slippage)
- For debugging only.

### 9.2 Fixed slippage
Example:
```
slippage_bps = 2 → 0.02%
fill_price = price * (1 ± slippage)
```

### 9.3 Volatility-dependent slippage
`slippage = ATR / price * k`

### 9.4 Spread simulation
Use historical bid/ask spread if available, or synthetic spread.

---

# 10. Execution Sync Model

Backtester emulates Execution Engine through:

- 1m micro-steps (if highest resolution available)
- correct order of SL/TP checks
- partial fill ordering
- idempotent behavior  
- SL priority over TP  
- multi-candle entry scenarios  

---

# 11. Pseudocode (Full Version)

```python
def run_backtest(start, end, initial_equity):
    equity = initial_equity

    for T in generate_5m_steps(start, end):

        snapshot = build_snapshot(T)
        flow = build_flow(T)

        decision = decision_engine(snapshot, flow, account_state(equity))

        save_decision(decision)

        fills = simulate_execution(decision, candles, slippage_model)

        for fill in fills:
            equity += fill.realized_pnl - fill.fee
            save_trade(fill)

        save_equity_curve(T, equity)

    return full_results()
```

---

# 12. Validation & Debugging Modes

Backtester should offer:

### Verbose Mode  
Prints every step:
- decisions  
- entries  
- fills  
- SL/TP sequences  

### Compare Mode  
Run two versions side-by-side:
```
backtest v1  
backtest v2  
→ produce diff report
```

### Dry-Run Mode  
Runs everything except heavy SQL writes.

---

# 13. Output Files

Backtester may also export:

- CSV of trades  
- CSV of equity curve  
- Charts:
  - equity vs time  
  - DD vs time  
  - histogram of R-multiples  

These can be displayed on Dashboard or downloaded.

---

# 14. Summary

Backtesting Engine provides:

- faithful reproduction of live pipeline  
- deterministic simulation  
- realistic execution model  
- full analytical insights  
- multi-version strategy evaluation  
- data stored in dedicated *_backtest tables  

Together with:

- `DATABASE_SCHEMA.md`  
- `DECISION_ENGINE.md`  
- `EXECUTION_ENGINE.md`  
- `RISK_MANAGER.md`

this module completes the **research and evaluation layer** of the AI Trading Showdown Bot.

