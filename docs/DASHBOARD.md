# AI Trading Showdown Bot – Dashboard Specification

Version: 1.0  
Status: Fully aligned with ARCHITECTURE, INPUT_FORMATS, DATA_PIPELINE, DECISION_ENGINE, EXECUTION_ENGINE, RISK_MANAGER.

---

# 1. Purpose

The **Dashboard** is the operational interface of the AI Trading Showdown Bot.  
It provides:

- real-time monitoring of system state,
- manual data input (ETF, liquidation map, sentiment),
- diagnostics & logs,
- visibility into decisions, flows, executions, risk state,
- tools for debugging & backtesting results.

Dashboard does **not** make decisions or execute trades.  
It is an **observability + input control layer** built on top of the bot.

---

# 2. Architecture Overview

Dashboard consists of:

1. **Backend API (FastAPI / Flask)**  
   - CRUD endpoints for manual inputs  
   - read-only endpoints for system state  
   - authentication + permissions  

2. **Frontend UI**  
   - Single-page or multi-page interface  
   - Auto-refreshing data panels  
   - JSON editors & validators  

3. **Data Sources**  
   - `/data/*.json` current input files  
   - MariaDB historical tables  
   - recent logs & diagnostics  

---

# 3. Main Dashboard Sections

The Dashboard includes **7 major sections**:

```
1. System Status
2. Market Snapshot
3. Flow Diagnostics
4. Decision Monitor
5. Position & Execution Monitor
6. Manual Inputs (ETF / Liq map / Sentiment)
7. Logs & Diagnostics
```

Below — full specification.

---

# 4. Section 1 — System Status

### Purpose  
Give the user complete clarity whether the bot is operating normally.

### Displayed fields

| Field | Source | Description |
|-------|--------|-------------|
| Bot Status | internal healthcheck | `RUNNING / IDLE / ERROR / RISK_OFF` |
| Analytics Loop (5m) timestamp | `btc_snapshot.json` | Last snapshot time |
| Flow timestamp | `btc_flow.json` | Last flow update |
| Decision timestamp | `decision.json` | Time of last decision |
| Execution loop status | execution engine heartbeat | Online/offline |
| Risk Mode | Risk Manager | `risk_off / neutral / cautious / aggressive` |
| Daily PnL / Weekly PnL | MariaDB equity_curve | For DD validations |
| Open Orders | Binance sync | Count and details |
| Open Position | Binance sync | Size, side, avg price |
| Last Reconciliation | reconciliation log | Timestamp + anomalies |

### Visual cues
- Green → all good  
- Yellow → warnings  
- Red → error / stale data / risk_off  

---

# 5. Section 2 — Market Snapshot (`btc_snapshot.json`)

### Sample preview fields:

- timestamp  
- current price  
- last 5m candle O/H/L/C  
- volatility (ATR levels)  
- market structure (HH/HL/LH/LL)  
- momentum (impulse / fading / choppy + score 0–1)  
- session (ASIA / EU / US)

### UI features:
- JSON preview panel  
- Interpretation panel (“Market currently forming HL above demand zone…”)  
- Sparkline for last 2–3 hours of prices  

---

# 6. Section 3 — Flow Diagnostics (`btc_flow.json`)

Shows the flow engine components:

- **Derivatives**
  - OI trend  
  - funding  
  - CVD divergence  
- **ETF summary**
  - last 3/7 day totals  
  - bullish/bearish signal  
- **Liquidation map**
  - strongest zones above/below price  
  - strength indicators (heatmap bar)  
- **Crowd / Trap index**
- **Sentiment score**
- **Warnings list**

A collapsible JSON view is available for full flow context.

---

# 7. Section 4 — Decision Monitor (`decision.json`)

Shows the last decision, including:

| Parameter | Meaning |
|----------|---------|
| `action` | long / short / flat |
| `entry_zone` | [min, max] |
| `sl` | stop-loss price |
| `tp1`, `tp2` | take profit levels |
| `position_size_usdt` | calculated size |
| `leverage` | applied leverage |
| `confidence` | 0–1 score |
| `risk_checks` | which checks passed/failed |
| `reason` | short textual reason |
| `risk_level` | 0–5 |

### Additional UI features:

- Color coding:  
  - green = long bias  
  - red = short bias  
  - grey = flat  
- Timeline view of decisions for last 24h  
- “Why this action?” explanation (plain-text summary)

---

# 8. Section 5 — Position & Execution Monitor

Shows:

### Open Position
- side (LONG/SHORT)  
- entry price  
- size  
- leverage  
- SL & TP’s  
- unrealized PnL  
- liquidation price  
- trade duration  

### Open Orders

Table:

| ID | Type | Side | Price | Qty | Status | Age |
|----|------|------|-------|-----|--------|-----|

### Execution Diagnostics
Displays signals from Execution Engine:

- chase events  
- market-fallback triggers  
- SL/TP recreation events  
- reconciliation warnings  
- partial fill messages  

Graph visualization (optional):
- current price vs SL/TP levels  
- entry zone heatmap  

---

# 9. Section 6 — Manual Inputs

## 6.1 ETF Flows

UI:

- Textarea for JSON paste
- “Validate JSON”
- “Save to system”

On save:

- file → `/data/btc_etp_flow.json`
- DB → `etp_flows` row insert
- new warning cleared in analytics loop

Validation errors shown inline.

---

## 6.2 Liquidation Map

UI identical to ETF:

- Textarea for JSON  
- Validation  
- Storage → `/data/btc_liquidation_map.json`  
- DB snapshot → `liquidation_zones_history`

Warnings shown if:

- zones contradict current price  
- stale timestamp  
- strength outside 0–1  

---

## 6.3 Sentiment Input

Form fields:

- Score (-2…+2 slider)  
- Label auto-generated  
- Comment  
- Save button  

On save:

- file → `/data/news_sentiment.json`
- DB → `news_sentiment_history`

Sentiment immediately affects the next flow.

---

# 10. Section 7 — Logs & Diagnostics

### Log streams

1. **Analytics logs**
2. **Decision logs**
3. **Execution logs**
4. **Warnings logs**
5. **Errors log**

All logs also stored in DB (`logs` table).

### Diagnostics panels:

- Data freshness monitor  
- ETF/liq/sentiment validation status  
- Table integrity checks  
- Reconciliation anomalies:
  - orphan positions  
  - phantom positions  
  - missing SL  
  - orphan orders  

### Filters:

- by level (INFO / WARNING / ERROR)  
- by component  
- by time window  

---

# 11. Backend API Specification (High Level)

### GET Endpoints (read-only)
```
GET /api/status
GET /api/snapshot
GET /api/flow
GET /api/decision
GET /api/position
GET /api/orders
GET /api/logs?level=ERROR
GET /api/backtest/runs
GET /api/backtest/run/{id}
```

### POST Endpoints (manual input)
```
POST /api/input/etf
POST /api/input/liquidations
POST /api/input/sentiment
```

### PUT / PATCH (future)
```
PATCH /api/config/risk
PATCH /api/config/engine
```

All modifying endpoints require authentication.

---

# 12. Authentication & Security

Dashboard must include:

- login/password or token-based auth
- HTTPS-only operation
- rate limiting (optional)
- IP allowlist for admin access
- protection against direct writes to `/data/*.json` from public

---

# 13. Refresh & Polling Strategy

For monitoring sections:
- Poll every 5–10 seconds for state (`status`, `snapshot`, `flow`, `decision`, `execution`)
- Logs streamed with pagination
- Heavy sections (charts, backtests) refresh on demand

---

# 14. Future Features (Optional)

### Historical charts
- price vs SL/TP  
- flow indicators  
- trade markers  

### Integrated backtest viewer
- interactive equity curve  
- drawdown graph  
- list of simulated trades  

### Strategy comparison tool
- A/B testing mode  
- overlay of two equity curves  

---

# 15. File Structure for Dashboard

```
src/dashboard/
    api.py
    auth.py
    routers/
        inputs.py
        status.py
        decisions.py
        execution.py
        logs.py
        backtest.py
    ui/
        index.html
        css/
        js/
```

---

# 16. Summary

Dashboard is the **central operational console** of the bot, providing:

- live visibility into the pipeline,
- full manual control of ETF/liquidation/sentiment inputs,
- ability to diagnose issues,
- clear insights into decisions and execution,
- integration with logs & backtest results.

It is **non-critical to the trading flow**, but essential for reliability, transparency, and human oversight.

