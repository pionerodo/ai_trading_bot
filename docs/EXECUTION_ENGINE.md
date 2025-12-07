# AI Trading Showdown Bot – Execution Engine Specification

Version: 1.0  
Status: Fully aligned with Technical Specification (incl. section 13: Execution Improvements)

---

# 1. Purpose

The **Execution Engine** is the module that transforms *decisions* into *actual orders and positions* on Binance Futures.

It is **stateful, real‑time**, and must be:

- **fault‑tolerant**  
- **idempotent**  
- **safe under network/API failures**  
- **consistent** with portfolio state  
- able to **recover from restarts** without losing control of open positions  

Execution Engine runs continuously in a **1–3 second loop**, completely independent of the **5‑minute Analytics Loop**.

---

# 2. Architectural Principles

Execution Engine is designed according to these strict principles:

### ✔ 1. **It never performs analytics or decision‑making.**
It only consumes the latest `decision.json`.

### ✔ 2. **It does not question the directional idea** (long/short/flat).  
But it **can** refuse to execute if:

- local risk limits are violated  
- required price conditions are invalid  
- decision outdated or malformed  
- account is out of sync with Binance  

### ✔ 3. **It must be idempotent.**
Re-sending the same decision must *not* create duplicate orders.

This is enforced using:

- unique `newClientOrderId`  
- deterministic order naming conventions  
- reconciliation before order placement  

### ✔ 4. **It must ALWAYS restore SL/TP on open positions.**

### ✔ 5. **It must handle partial fills gracefully**.

### ✔ 6. **It must support full restart & recovery**  
(see section “Reconciliation”).

---

# 3. High-Level Execution Flow

```
decision.json (5m updates)
              |
              v
      Execution Engine (1–3s)
  -------------------------------------------------
   Read decision → Sync state → Manage entries →
   Manage SL/TP → Handle fills → Log → Repeat
  -------------------------------------------------
```

This engine is effectively a **continuous order manager**.

---

# 4. Components

The Execution Engine consists of:

1. **State Manager**
2. **Order Factory (idempotent order builder)**
3. **Entry Logic**
4. **SL/TP Logic**
5. **Chase Logic**
6. **Fail-Safe Market Fill Logic**
7. **Partial Fill Handler**
8. **Reconciliation Engine**
9. **Error Handling & Telegram Alerts**
10. **Logging Subsystem**

---

# 5. Real-Time Loop (Every 1–3 Seconds)

Pseudocode overview:

```python
while True:
    read decision
    read account state (position, equity)
    read open orders
    validate decision freshness

    if no position:
        manage_entry_orders()
    else:
        manage_sl_tp()
        manage_partial_fills()

    sleep(1-3 seconds)
```

Now described in detail.

---

# 6. Decision Validation

Before acting, engine ensures:

### ✔ Decision is not stale  
Max allowed age: `<= 10 minutes`.

If stale:

- engine cancels all non‑SL/TP orders,
- stays flat,
- logs warning.

### ✔ Decision is structurally valid  
Required fields:

- `action`
- `entry_zone`
- `sl`
- `position_size_usdt`
- `leverage`

If invalid → **flat mode**.

---

# 7. Entry Order Logic

If `action == "flat"` and no position → cancel all pending entries → idle.

If `action == "long"` or `"short"` and **no open position**:

### Task:
Place limit orders inside `entry_zone`.

Example:

```
entry_zone = [90700, 90900]
entry_mid = 90800
```

Typical implementation – **one limit order at the mid‑price**:

- Side: BUY for long, SELL for short  
- Price: `entry_mid`  
- Quantity: derived from `position_size_usdt`

### Idempotent Order IDs

Orders must use deterministic IDs:

```
capi_entry_001
capi_sl_001
capi_tp1_001
capi_tp2_001
```

Re-sending `capi_entry_001` does NOT create a duplicate.

### Entry Conditions

Entry orders must NOT be placed if:

- price too far from entry zone  
- spread abnormal  
- session = restricted  
- volatility above configured threshold  

This protects from accidental entries in extreme conditions.

---

# 8. Chase Logic (Limit Repositioning)

If the price moves moderately away from the limit entry, the engine may “chase” the price:

### Conditions for chase:
- price drift beyond `chase_threshold` (e.g., 0.1–0.25% of price)
- order has not filled after N seconds
- volatility is stable
- decision still valid

### Actions:
- Cancel old entry order
- Create new one closer to current price, but **not outside entry_zone**.

Chase ends if:

- price leaves entry zone  
- volatility spikes  
- decision changes  

---

# 9. Fail-Safe Market Entry (Optional but Critical)

In strong setups (high confidence), if:

- price is inside entry_zone  
- limit order fails to fill after several chase attempts  
- spread is narrow  

Engine MAY execute:

### → **Market Order Entry**

This is allowed only when:

```
confidence >= CONFIDENCE_FOR_MARKET_ENTRY
```

Typical: `>= 0.75`

Market entry prevents missing high‑quality trades.

---

# 10. SL/TP Logic

Once position is open, Execution Engine must:

### ✔ Ensure SL always exists  
If missing → create immediately.

### ✔ Ensure TP(s) exist  
If missing → recreate.

### ✔ Maintain idempotency  
SL/TP orders also use deterministic clientOrderId.

---

# 11. SL Drift / Reset Logic

SL may be adjusted if:

- Decision Engine gives updated SL (rare)
- Volatility shrinks (ATR decreases)
- First TP hits and SL must move to breakeven (v1.1 optional)
- Risk Manager requires tightening

SL must never move to increase risk.

---

# 12. TP & Partial Take Profit Handling

### If TP1 hit:
- close partial position (50% typical)
- reset SL to breakeven or slightly profitable (optional)
- remove TP1 order, keep TP2

### If TP2 hit:
- close remaining position
- remove all SL/TP orders

### Partial fills:
- Must be logged  
- Must update internal state  
- Must not cause order duplication  

---

# 13. Position State Machine

Execution engine maintains an internal simple state machine:

```
NO_POSITION
    ↓ entry fills
IN_POSITION
    ↓ sl/tp hit
POSITION_CLOSED
```

After closing, engine:

- cancels all remaining SL/TP orders  
- logs trade summary  
- becomes ready for new decision  

---

# 14. Reconciliation Engine (Critical Component)

Runs **on every startup** and periodically (e.g. every hour).

### Purpose:
Ensure DB and Binance are **synchronized**.

### Queries:
- `GET /fapi/v2/positionRisk`
- `GET /fapi/v1/openOrders`

### Tasks:

1. **Detect orphan positions**
   - Position exists on Binance but not in DB  
   → Create emergency record in DB  
   → Apply SL immediately  
   → Send Telegram alert  

2. **Detect phantom positions**
   - DB shows open, but Binance = 0 size  
   → Mark closed in DB  
   → Cancel SL/TP  

3. **Restore missing SL/TP**
   - If position open but no SL order exists  
   → Create SL instantly (high severity event)  

4. **Clean orphan orders**
   - Orders existing on Binance without DB reference  
   → Cancel  

### Logging:
Reconciliation summary always logged with:

- mismatches count  
- actions taken  
- warnings/errors  

### Telegram Alerts:
Sent when:

- orphan positions found  
- missing SL restored  
- execution errors  

---

# 15. Error Handling & Safety

Execution Engine must never crash silently.

### Categories:

#### ⚠ Soft Errors
- temporary network failure  
- Binance `-1003` rate limits  
- slippage too high  

→ retry, log warning, continue.

#### ❌ Hard Errors
- Binance API returns fatal error  
- account in inconsistent state  
- SL cannot be placed  
- unknown position status  

→ Enter **SAFE MODE**, stop new trades, send Telegram alert.

---

# 16. Logging Requirements

Each loop iteration logs:

- decision ID and timestamp  
- current price  
- position state  
- number of open orders  
- any order operations (place/cancel/fill)  

Separate log levels:

- INFO: normal behaviour  
- WARNING: delays, retries, spreads  
- ERROR: reconciliation problems, API failures  
- CRITICAL: missing SL, orphan positions  

Logs stored in:

- `logs/engine.log`  
- DB `logs` table (structured events)  

---

# 17. Interaction With Risk Manager

Execution Engine must apply **local risk checks** even if Decision Engine approved a trade.

Reasons to override decision:

- price moved too far → risk too high  
- leverage too high due to price drift  
- equity smaller than expected  
- daily DD exceeded since last decision  

Engine may enforce:

- no entry (flat override)  
- reduced position size  
- forced SL tightening  

---

# 18. Execution Engine Pseudocode (Full Version)

```python
def execution_loop():
    reconcile_on_startup()

    while True:
        decision = load_decision()
        position = get_binance_position()
        orders = get_open_orders()

        validate_decision(decision)

        if no_position(position):
            cancel_invalid_orders(orders)
            if decision.action in ["long", "short"]:
                manage_entry_orders(decision, position, orders)
        else:
            manage_sl_tp(position, decision, orders)
            manage_partial_fills(position, orders)

        sleep(LOOP_INTERVAL)
```

---

# 19. Idempotent Order Model

All orders must be uniquely identified by *semantic role*:

```
capi_entry_<timestamp or decision_id>
capi_sl_<decision_id>
capi_tp1_<decision_id>
capi_tp2_<decision_id>
```

Thus:

- retrying the same request **never creates duplicates**
- reconciliation can always match orders to decisions  

---

# 20. Binance Restrictions & Compliance

Execution Engine must handle:

- minimum order sizes  
- tick sizes  
- position mode (hedge disabled = one-way mode)  
- USDT-M futures only  
- leverage from config  

If Binance rejects:

- adjust quantity to nearest valid step  
- log warning  
- retry  

---

# 21. Lifecycle of a Single Trade (Example)

```
Decision LONG → Execution Engine:
    → place entry limit
    → chase entry (up to threshold)
    → market fill if needed
    → upon fill:
         → place SL
         → place TP1, TP2
    → monitor
    → TP1 hits:
         → partial close
         → move SL to BE
    → TP2 hits:
         → final close
         → cancel remaining orders
    → log trade summary
    → wait for next decision
```

---

# 22. Summary

Execution Engine:

- runs independently at 1–3s intervals  
- consumes deterministic decisions from analytics  
- manages real orders safely and idempotently  
- enforces SL/TP at all times  
- handles entry, chase, market fallback  
- performs **full reconciliation** on startup  
- integrates tightly with Risk Manager  
- logs and alerts all anomalies  

This document specifies the exact operational behaviour required for a **production‑grade crypto execution system**.

Combined with:

- `DECISION_ENGINE.md`  
- `RISK_MANAGER.md`  
- `DATA_PIPELINE.md`  
- `DATABASE_SCHEMA.md`

it describes the complete trading logic pipeline.
