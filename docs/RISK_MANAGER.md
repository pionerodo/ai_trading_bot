# AI Trading Showdown Bot – Risk Manager Specification

Version: 1.0  
Status: Fully aligned with Technical Specification (including critical improvements)

---

# 1. Purpose

The **Risk Manager** is the security system of the trading engine.

Its goal is not to pick trade direction (that is Decision Engine’s job), but to ensure:

- the bot **never exceeds allowed risk**,  
- **daily and weekly drawdowns are limited**,  
- trades occur only during acceptable market conditions,  
- position sizes are always consistent with risk,  
- leverage stays within safe boundaries,  
- execution is stopped when safety is compromised.

Risk Manager is a **hard gate** around the Decision Engine and Execution Engine.

It can:

- block a trade → return `action = "flat"`  
- reduce trade size  
- limit leverage  
- override confidence  
- force SL tightening  
- enforce complete **risk-off** mode

---

# 2. Core Philosophy

Risk Manager is based on several principles:

### ✔ **Capital preservation > opportunity**
No signal justifies violating hard risk constraints.

### ✔ **Strict DD limits**
Once a limit is hit → **no new trades**, regardless of signal quality.

### ✔ **Unified sizing formula (ATR-based)**
All position sizing is volatility-normalized.

### ✔ **Session, news, ETF and derivatives filters**
Low liquidity or dangerous regimes reduce or eliminate risk-taking.

### ✔ **Global risk modes**
The entire system operates under one of several modes:
- `risk_off`
- `neutral`
- `cautious_risk_on`
- `aggressive_risk_on`

Modes affect:
- leverage  
- max position size  
- whether entries are allowed  

---

# 3. Inputs

Risk Manager receives:

1. **Account State**
   - balance (equity)
   - unrealized and realized PnL
   - daily PnL / DD
   - weekly PnL / DD
   - number of trades today

2. **Decision Engine candidates**
   - long_candidate
   - short_candidate
   - their scores and directional reasons

3. **Flow context (`btc_flow.json`)**
   - derivatives (funding, OI, CVD)
   - ETF summary
   - liquidation zones
   - crowd / trap
   - warnings
   - global risk score

4. **Snapshot context (`btc_snapshot.json`)**
   - volatility (ATR)
   - session
   - market structure and momentum

5. **Configuration params**
   - max daily DD
   - max weekly DD
   - risk per trade %  
   - leverage caps for each mode  
   - session rules  
   - volatility rules  

---

# 4. Outputs

Risk Manager produces:

### 1. Boolean flags (exposed in decision.json → `risk_checks`)
```
{
    "daily_dd_ok": true,
    "weekly_dd_ok": true,
    "max_trades_per_day_ok": true,
    "session_ok": true,
    "no_major_news": false
}
```

### 2. Risk Mode
One of:
- `"risk_off"`
- `"neutral"`
- `"cautious_risk_on"`
- `"aggressive_risk_on"`

### 3. Adjusted values for:
- position size  
- leverage  
- risk_level  
- confidence  

### 4. Hard override (if necessary)
- convert ANY action → `"flat"`  
- position size = 0  
- leverage = 0  

---

# 5. Hard Risk Constraints (Non-Negotiable)

These are the **immutable safety rules**.

## 5.1 Daily Drawdown Limit

Default example:

```
MAX_DAILY_DD = -2%
```

If equity today drops below:

```
equity_start_of_day * 0.98
```

→ **STOP TRADING**

Effects:

- `daily_dd_ok = false`
- Decision Engine must output: `action = "flat"`
- Execution Engine must not open new positions
- Telegram alert is triggered
- Trades allowed only next day (configurable reset)

---

## 5.2 Weekly Drawdown Limit

Default:

```
MAX_WEEKLY_DD = -5%
```

If weekly DD breached:
- no new entries until next week
- internal mode = `"risk_off"`  
- system remains active only for managing existing positions

---

## 5.3 Max Trades Per Day

Typical limit:

```
MAX_TRADES_PER_DAY = 3
```

If exceeded:
- `max_trades_per_day_ok = false`
- new trades blocked

Prevents overtrading and emotional churning.

---

## 5.4 Mandatory SL

No position may exist without an SL.

If SL is missing:
- Risk Manager triggers **critical flag**
- Execution Engine must place SL immediately

---

# 6. Global Risk Modes

Risk mode represents the system’s current “appetite”.

### 6.1 `risk_off`
Triggered if:

- DD limits violated
- Derivatives extremely overheated
- ETF flows extremely negative
- High-volatility shock
- News sentiment extremely negative
- Liquidity extremely thin

Restrictions:

- No new entries  
- Only emergency management  
- Leverage 0  
- Risk level forced to 0  
- Confidence forced to 0  

---

### 6.2 `neutral`
Normal operational mode.  
No special restrictions.

Leverage cap:  
```
<= 3x
```

---

### 6.3 `cautious_risk_on`
Triggered when:

- ETF mixed but not negative
- Momentum mild
- Session low-volume (ASIA)
- Funding slightly elevated

Effects:

- Position size reduced by 30–50%
- Leverage cap: 2x
- Confidence multiplier = 0.8

---

### 6.4 `aggressive_risk_on`
Allowed only when:

- snapshot + flow strongly aligned  
- ETF strongly supportive  
- liq asymmetry clear  
- volatility moderate  
- no warnings  

Effects:

- Leverage cap: 5x  
- Position size multiplier = 1.3  
- Confidence multiplier = 1.2  

Used sparingly.

---

# 7. ATR-Based Position Sizing (Core Formula)

The system uses volatility-normalized sizing:

## 7.1 Step 1 — Compute SL distance

```
sl_distance = max(
    k1 * ATR_tf,
    distance_to_structure_support/resistance
)
```

Typical `k1` = 1.5–2.0.

## 7.2 Step 2 — Compute risk in USDT

```
risk_usdt = equity * risk_percent
```

Typical `risk_percent` = 0.005 (0.5%).

## 7.3 Step 3 — Compute position notional

```
position_size_usdt = risk_usdt / sl_distance
```

## 7.4 Step 4 — Apply leverage caps

```
max_pos_usdt = equity * max_leverage_mode
position_size_usdt = min(position_size_usdt, max_pos_usdt)
```

## 7.5 Step 5 — Round to valid Binance step

All quantities must obey:

- step size  
- min notional  
- precision constraints  

---

# 8. SL / TP Risk Rules

## 8.1 Stop-Loss Rules

SL must be:

- outside noise (ATR-based)
- below last HL (for longs)
- above last LH (for shorts)
- never widened after position entry (no increasing risk)

## 8.2 Take-Profit Rules

TP1 and TP2 are based on:

- multiples of SL distance (1.5R, 3R)
- nearby structural levels
- liq clusters (e.g. TP near major liquidation zone)

## 8.3 Breakeven Logic (optional, enabled for v1.1)

After TP1 hit:
- SL moves to breakeven or better  
- reduces risk to zero  

---

# 9. Derivatives-Based Risk Filters

The following conditions increase risk or force flat mode:

### 9.1 Extreme Funding
If funding > threshold (e.g. 0.03% per 8h):
- longs discouraged  
- risk mode downgraded  
- warning generated  

### 9.2 Extreme OI
Surging OI as price goes up can indicate crowded longs.

### 9.3 CVD Divergence
If CVD direction contradicts price movement significantly:
- confidence reduced  
- possible flat override  

---

# 10. ETF Flow Overrides

ETF flows are a major macro signal.

### 10.1 Positive ETF flows
Increase:

- risk_level  
- confidence  
- allowed leverage  

### 10.2 Strong multi-day inflows
Enable “aggressive_risk_on” mode if other signals confirm.

### 10.3 Strong outflows
Force:

- confidence = 0  
- action = flat  

unless liquidity map clearly supports mean-reversion or traps.

---

# 11. Liquidation Map-Based Risk Filters

### 11.1 Strong clusters against planned direction
Example: planning a long but strong long-liq cluster directly above → dangerous.

Effects:
- reduce size  
- reduce leverage  
- may force flat  

### 11.2 Asymmetry as a risk reducer
If strong short clusters below → long becomes safer.

---

# 12. Sentiment Filter

If sentiment strongly negative (`score <= -2`):

- reduce confidence  
- reduce size  
- force flat if ETF/derivatives also negative  

If sentiment strongly positive:

- cautious support for longs unless contradicted by derivatives.

---

# 13. Session Filter

### Restrictions:
- Early ASIA session: low liquidity  
→ reduce size or avoid new trades  

- Post-US close lull: low volume  
→ avoid except high-conviction setups  

### Allowed:
- EU / US main sessions  
→ normal/aggressive risk modes allowed  

---

# 14. Volatility Filter

If ATR or realized volatility exceeds threshold:

- shrink position sizes  
- lower leverage  
- avoid market entries  
- consider flat-mode  

If volatility too low:

- avoid trading due to poor R/R  
- consider skipping (flat)  

---

# 15. Risk Checks Integration

Each cycle Risk Manager runs:

```
daily_dd_ok
weekly_dd_ok
max_trades_per_day_ok
session_ok
no_major_news
```

Decision Engine consumes these flags:

- if any **critical** = false → output `action = "flat"`

Execution Engine also verifies them before any entry.

---

# 16. Confidence Modifier

Final decision confidence =

```
raw_confidence
    * mode_confidence_multiplier
    * sentiment_modifier
    * (1 - warning_penalty)
```

Ranges:
- 0 → never execute  
- >0.7 → can allow market entry (fail-safe fill)  
- >0.8 → aggressive mode potential  

---

# 17. Risk Manager Pseudocode

```python
def risk_manager(account, snapshot, flow, config, today_stats):
    checks = {
        "daily_dd_ok": account.daily_dd > config.max_daily_dd,
        "weekly_dd_ok": account.weekly_dd > config.max_weekly_dd,
        "max_trades_per_day_ok": today_stats.trades < config.max_trades_per_day,
        "session_ok": snapshot.session.current in config.allowed_sessions,
        "no_major_news": flow.news_sentiment.score > -2
    }

    # Determine mode
    if not checks["daily_dd_ok"] or not checks["weekly_dd_ok"]:
        mode = "risk_off"
    elif flow.risk.global_score < 0.3:
        mode = "neutral"
    elif flow.risk.global_score < 0.6:
        mode = "cautious_risk_on"
    else:
        mode = "aggressive_risk_on"

    return checks, mode
```

Position sizing then depends on mode.

---

# 18. Emergency Risk Behaviour

Triggers:
- missing SL  
- orphan position  
- Binance API outage  
- extreme volatility spike  
- equity mismatch  

Actions:
- flatten orders  
- tighten SL  
- suspend entries  
- notify via Telegram  
- enter `"risk_off"` until manual confirmation  

---

# 19. Summary

Risk Manager is the **enforcement layer** of the entire trading bot.

It guarantees:

- account safety  
- consistent sizing  
- correct leverage  
- proper filtering of dangerous sessions/regimes  
- probablistic weighting of signals via confidence  
- ETF/liquidation/derivatives integration  
- absolute compliance with drawdown constraints  

Without the Risk Manager, the trading engine would be unstable.  
With it, the bot behaves like a disciplined professional system.

This specification completes the trio with:

- `DECISION_ENGINE.md`  
- `EXECUTION_ENGINE.md`  

and forms the full logic core of the AI trading engine.

