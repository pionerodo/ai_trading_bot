# AI Trading Showdown Bot – Decision Engine Specification

Version: 1.0  
Status: Aligned with core Technical Specification

---

## 1. Purpose

The **Decision Engine** is the brain of the AI Trading Showdown Bot.

Its responsibilities:

1. Take the latest **market snapshot** (`btc_snapshot.json`) and **flow context** (`btc_flow.json`).
2. Optionally consider:
   - current account / position state (from DB / Binance),
   - global risk mode and limits (Risk Manager).
3. Produce a **deterministic trading decision**:

   - go **long**,  
   - go **short**, or  
   - stay **flat**,

   together with:

   - entry zone (price band),
   - SL / TP levels,
   - position size and leverage,
   - confidence score,
   - risk check flags,
   - a concise explanation string.

The Decision Engine runs as part of the **5-minute Analytics Loop**:

```text
btc_snapshot + btc_flow + account_state
        |
        v
   Decision Engine
        |
        v
    decision.json   +   decisions table in DB
```

---

## 2. Inputs and Outputs

### 2.1 Inputs

1. **Market snapshot** (`btc_snapshot.json`) – see `DATA_PIPELINE.md`:
   - current price,
   - multi-timeframe candles,
   - market structure (HH-HL / LL-LH / range),
   - momentum (state + score per TF),
   - session and volatility regime.

2. **Flow context** (`btc_flow.json`):
   - derivatives (OI, funding, CVD),
   - ETF summary,
   - liquidation zones,
   - crowd bias,
   - trap index,
   - warnings,
   - global risk mode.

3. **Account and trading state** (from DB and/or Binance):

   - current **net position** for BTCUSDT:
     - side, size, entry price,
     - SL/TP status.
   - realized PnL, daily and weekly PnL / DD.
   - number of trades opened today.
   - equity (wallet balance + unrealized).

4. **Risk Manager configuration** (from config / DB):

   - allowed daily/weekly DD,
   - max trades per day,
   - risk-per-trade percent,
   - caps for leverage per risk mode,
   - behaviour in high-risk / high-vol regimes.

---

### 2.2 Output: `decision.json`

The main output is a JSON object with the following structure (see also `DATA_PIPELINE.md`):

```json
{
  "symbol": "BTCUSDT",
  "timestamp_iso": "2025-11-28T10:05:00Z",

  "action": "long",
  "reason": "trend_up_multi_tf_with_etf_support_and_liq_below",

  "entry_zone": [90700.0, 90900.0],
  "sl": 89800.0,
  "tp1": 92200.0,
  "tp2": 93500.0,

  "risk_level": 3,
  "position_size_usdt": 1000.0,
  "leverage": 3,

  "confidence": 0.76,

  "risk_checks": {
    "daily_dd_ok": true,
    "weekly_dd_ok": true,
    "max_trades_per_day_ok": true,
    "session_ok": true,
    "no_major_news": false
  }
}
```

Key fields:

- `action` – **mandatory**; one of:
  - `"long"`,
  - `"short"`,
  - `"flat"`.

- `reason` – short text label (snake_case) explaining the decision.

- `entry_zone` – price band `[min, max]` for initial limit entries.
- `sl` – stop-loss.
- `tp1`, `tp2` – optional take-profit targets.

- `risk_level` – discrete risk level (1–5).
- `position_size_usdt` – notional order size in USDT.
- `leverage` – target leverage, limited by risk manager.

- `confidence` – 0–1, summarising quality and alignment of all signals.

- `risk_checks` – boolean flags from risk manager:

  - `daily_dd_ok`,
  - `weekly_dd_ok`,
  - `max_trades_per_day_ok`,
  - `session_ok`,
  - `no_major_news`.

If **any critical check fails**, the Engine should typically produce `"action": "flat"`; alternatively it may encode a “suggested” direction but mark it as unusable for live execution.

In addition to JSON, the decision is written as a row into DB `decisions` table.

---

## 3. Decision Cycle

Each 5-minute cycle, Decision Engine performs the following steps:

1. **Load inputs**
   - Latest `btc_snapshot` (from JSON/DB).
   - Latest `btc_flow`.
   - Current account and position state.
   - Current risk config and day/week statistics.

2. **Compute directional bias candidates**
   - Evaluate **LONG** candidate.
   - Evaluate **SHORT** candidate.
   - Compute scores and reasons for each.

3. **Resolve conflicts**
   - If both LONG and SHORT look strong → treat as **conflict** and produce FLAT.
   - If both weak → FLAT.
   - If one is strong and the other clearly invalid → choose the strong one.

4. **Apply risk manager**
   - Compute daily and weekly DD flags.
   - Check max trades per day limits.
   - Check allowed sessions.
   - Consider ETF, liqs and sentiment overrides.
   - Possibly downgrade action to FLAT or lower risk_level.

5. **Compute position size and SL/TP**
   - Use ATR and structure levels (from snapshot) to define SL distance.
   - Use risk-per-trade formula to compute size.
   - Define TP levels based on volatility and structure.

6. **Compute final confidence**
   - Combine:
     - strength of structure,
     - momentum agreement,
     - derivatives consistency,
     - ETF support or headwind,
     - liq map support,
     - sentiment alignment,
     - absence of critical warnings.

7. **Emit decision**
   - Save `decision.json`.
   - Insert row into `decisions` table.
   - Log human-friendly summary.

---

## 4. Long / Short / Flat Logic – High-Level Rules

### 4.1 Long Candidate

LONG candidate is considered when all the following directional criteria are reasonably satisfied:

1. **Market structure (trend bias)**

   - On key TFs (5m, 15m; optionally 1h):
     - `market_structure.tf_5m` in {`"HH-HL"`, `"range"`}
     - `market_structure.tf_15m` in {`"HH-HL"`, `"range"`}
   - Bearish structure on 1h is tolerable if lower TFs are strong and the trade is defined as scalp with clear liquidity below.

2. **Momentum**

   - `momentum.tf_5m.state` in {`"impulse_up"`, `"fading"`}
   - `momentum.tf_5m.score` above a minimal threshold (e.g. > 0.55 for clean impulse).
   - Higher TFs (15m, 1h) ideally not strongly opposed (e.g. avoid `impulse_down` with high score).

3. **Derivatives Context**

   - Funding is not extremely positive:
     - `funding.current` not far above its normal range.
   - OI:
     - rising OI with rising price = supportive, but must be checked for overheating.
   - CVD:
     - not strongly diverging against price for the chosen direction.

4. **ETF Flows (etp_summary)**

   - Ideally:
     - `last_3d_total` ≥ 0 **and/or**
     - `signal` in {`"bullish"`, `"bullish_reversal"`, `"bearish_exhaustion"`}
   - Strong ongoing outflows are a negative factor; they reduce risk_level or confidence.

5. **Liquidation Map**

   - Presence of **strong short-liquidation clusters BELOW** current price is bullish:
     - supports idea of fake breakdowns / squeezes against shorts.
   - **Strong long liq cluster directly above** can cap the upside: either trade is cautious or FLAT.

6. **Crowd & Trap**

   - If `crowd.bias_side == "short"` and `trap_index.side == "short"` with decent scores:
     - indicates trapped shorts → supports long.
   - If crowd and trap clearly against long (much fuel above, everyone already long), long is discouraged.

7. **Sentiment**

   - `news_sentiment.score >= 0` (neutral or better) is preferable.
   - Strongly negative sentiment is a headwind and lowers confidence.

8. **Warnings**

   - No severe `"extreme_funding"` against the long idea.
   - No `"etf_strong_outflow"` against trend.
   - No combination of critical warnings that push overall risk to “risk_off”.

If the above are mostly aligned, a LONG candidate is formed.  

If too many factors contradict, the LONG candidate is rejected or low-confidence.

---

### 4.2 Short Candidate

SHORT candidate is conceptually symmetric:

1. **Market structure**
   - `market_structure.tf_5m` in {`"LL-LH"`, `"range"`}
   - `market_structure.tf_15m` in {`"LL-LH"`, `"range"`}
   - Higher TF (1h) may be bullish but with signs of exhaustion / traps above.

2. **Momentum**
   - `momentum.tf_5m.state` in {`"impulse_down"`, `"fading"`}
   - Score above threshold in down direction.
   - Higher TFs not strongly pushing up.

3. **Derivatives**
   - Overly positive funding with price at highs:
     - open door for short mean-reversion.
   - OI high / rising with price = potentially overleveraged longs.

4. **ETF**
   - Strong outflows (`last_3d_total` << 0, `signal` like `"bearish"`) support shorts.
   - Persistent inflows reduce risk or disqualify the short.

5. **Liquidation Map**
   - Strong **long liq clusters ABOVE** current price support short scenario:
     - market can be pulled upwards to liquidate longs and then reverse.
   - Strong short clusters below might limit downside reward.

6. **Crowd & Trap**
   - If `crowd.bias_side == "long"` and `trap_index.side == "long"`:
     - many trapped longs → good for short.
   - If crowd/trap align against short, idea is weaker.

7. **Sentiment and warnings**
   - Extremely bullish news + ETF inflows can reduce the validity of a short.
   - Extreme negative sentiment with heavy outflows can support trend shorts.

---

### 4.3 Flat Conditions

The Decision Engine must be **comfortable with staying flat**.

It must choose `action = "flat"` when:

1. **Strong conflict of signals**
   - Snapshot supports long but flow strongly supports short, or vice versa.
   - Important metrics disagree (e.g. structure up, but ETF+derivatives+liq all scream down).

2. **Insufficient structure / choppy regime**
   - Market structure = `"range"` on all TFs.
   - Momentum is `choppy` or `neutral` with low scores.
   - No clear asymmetry in liq or ETF.

3. **Risk constraints violated**
   - daily or weekly DD limits hit;
   - too many trades already taken today;
   - risk mode is effectively `risk_off` due to external conditions.

4. **Weak overall confidence**
   - Long and short candidate scores are both low (< some threshold).
   - Or both sides have huge trade-offs and no clear edge.

In FLAT mode, the **Execution Engine** may:

- keep current positions managed (e.g. trailing/unwinding),
- but the Decision Engine does **not** propose new entries.

---

## 5. Scoring and Confidence

While the Decision Engine is rule-based, it is useful to think in terms of **scores**:

- `score_long` – aggregated score for long candidate.
- `score_short` – aggregated score for short candidate.

Possible components:

- `structure_score` – how clean the trend is.
- `momentum_score` – strength of momentum in that direction.
- `derivatives_score` – how supportive derivatives are.
- `etf_score` – ETF flows and signal alignment.
- `liq_score` – asymmetric liquidity support.
- `crowd_trap_score` – crowd positioning.
- `sentiment_score` – news and social.

Each component is normalized (e.g. 0–1).  
Overall:

```text
score_long  = weighted_sum_long(...)
score_short = weighted_sum_short(...)
```

Then:

- If `score_long` and `score_short` both low → FLAT.
- If `score_long` >> `score_short` → LONG (if risk checks pass).
- If `score_short` >> `score_long` → SHORT (if risk checks pass).
- If both high and close → treat as conflict → FLAT or very low size.

The final `confidence` field in `decision.json` can be set to:

```text
confidence = max(score_long, score_short) * risk_modifier
```

where `risk_modifier` accounts for:

- volatility regime,
- risk mode,
- warnings.

---

## 6. Integration with Risk Manager

The Risk Manager (specified in `RISK_MANAGER.md`) provides **constraints** and **modes** that wrap around the directional logic:

- Daily and weekly DD:
  - if exceeded → `daily_dd_ok` / `weekly_dd_ok = false`.
  - In this case normal behaviour is `action = "flat"` regardless of good setups.
- Max trades per day:
  - if reached → `max_trades_per_day_ok = false`.
- Session filter:
  - no trading during illiquid or “dead” sessions, unless in special mode.
- Global risk mode:
  - `risk_off` → no new entries.
  - `neutral` → normal behaviour.
  - `cautious_risk_on` → long/short allowed but with reduced size and leverage.
  - `aggressive_risk_on` → allow more risk if signals are extremely strong (but with hard DD caps).

From the Decision Engine’s perspective:

1. It first evaluates **pure directional** LONG/SHORT/FLAT candidates.
2. Then calls or uses Risk Manager to:
   - check risk_checks flags,
   - get allowed risk_level and leverage caps,
   - possibly override `action` to FLAT.

If Risk Manager blocks trading, Decision Engine:

- sets `action = "flat"` or at least `confidence` very low,
- keeps `risk_checks` reflecting which constraints failed.

---

## 7. SL/TP and Position Sizing Logic (Overview)

Full formulas are detailed in `RISK_MANAGER.md`; here is the contract-level overview.

### 7.1 Stop-Loss (SL)

- SL distance is derived from:
  - market structure (below last HL for long, above last LH for short),
  - ATR-based volatility band.

Typical approach:

```text
sl_distance = max(
  k1 * ATR_tf, 
  distance_to_structure_level
)
```

where `k1` is a configurable multiplier.

SL price:

- For long:  `sl = entry_mid - sl_distance`
- For short: `sl = entry_mid + sl_distance`

### 7.2 Take-Profits (TP1, TP2)

- TP targets can be based on:
  - multiples of SL distance (e.g. R=1.5, R=3),
  - nearby structural levels (prior swing high/low),
  - plus adjustments for liq clusters and ETF flows.

Example:

- `tp1 = entry_mid + 1.5 * sl_distance * dir`
- `tp2 = entry_mid + 3.0 * sl_distance * dir`

where `dir` is +1 for long, -1 for short.

### 7.3 Position Size

Risk per trade (capital at risk if SL hit):

```text
risk_usdt = equity * risk_percent
```

Position notional:

```text
position_size_usdt = risk_usdt / sl_distance
```

Then limited by:

- max notional allowed by account,
- max leverage allowed by mode:

```text
max_position_usdt = equity * max_leverage_mode
position_size_usdt = min(position_size_usdt, max_position_usdt)
```

All this is fed into `position_size_usdt` and derived `leverage` in `decision.json`.

---

## 8. Pseudocode

Below is a simplified pseudocode describing the overall flow:

```python
def make_decision(snapshot, flow, account_state, risk_config) -> Decision:
    # 1. Compute candidates
    long_candidate  = evaluate_long_candidate(snapshot, flow, account_state)
    short_candidate = evaluate_short_candidate(snapshot, flow, account_state)

    # 2. Compare and choose direction (pre-risk)
    dir_action, dir_confidence, dir_reason = resolve_direction(long_candidate, short_candidate)

    # 3. Apply risk manager
    risk_checks = run_risk_checks(account_state, risk_config)
    if not all_critical_ok(risk_checks):
        action = "flat"
        confidence = 0.0
        # still keep dir_reason for information/debugging
        reason = f"blocked_by_risk:{dir_reason}"
        entry_zone = None
        sl = tp1 = tp2 = None
        pos_size = 0.0
        leverage = 0
    else:
        action = dir_action
        confidence = dir_confidence

        if action in ("long", "short"):
            entry_zone = compute_entry_zone(snapshot, flow, action)
            sl = compute_sl(snapshot, flow, action, entry_zone)
            tp1, tp2 = compute_tps(snapshot, flow, action, entry_zone, sl)

            # compute position sizing and leverage
            pos_size, leverage, risk_level = compute_position_sizing(
                account_state, risk_config, entry_zone, sl, flow, action
            )
        else:
            entry_zone = None
            sl = tp1 = tp2 = None
            pos_size = 0.0
            leverage = 0
            risk_level = 0

        reason = dir_reason

    return Decision(
        symbol="BTCUSDT",
        timestamp_iso=now_utc_iso(),
        action=action,
        reason=reason,
        entry_zone=entry_zone,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        risk_level=risk_level,
        position_size_usdt=pos_size,
        leverage=leverage,
        confidence=confidence,
        risk_checks=risk_checks
    )
```

This pseudocode assumes:

- `evaluate_long_candidate` and `evaluate_short_candidate` compute detailed scores and reasons.
- `run_risk_checks` encapsulates daily/weekly DD, trades per day, session and news filters.
- `compute_position_sizing` uses ATR and risk configuration.

---

## 9. Edge Cases and Fallbacks

The Decision Engine must handle edge cases gracefully:

1. **Missing or invalid inputs**
   - If `btc_snapshot` or `btc_flow` are missing or obviously stale:
     - log ERROR,
     - return `action = "flat"` and `confidence = 0`.
2. **Stale external JSON (ETF, liqs, sentiment)**
   - If ETF/liqs/sentiment are too old:
     - downgrade their weight in scoring,
     - optionally add a warning.
3. **Account inconsistencies**
   - If equity or PnL cannot be fetched:
     - default to minimal risk setup,
     - or fully flat until fixed.
4. **Extreme regimes**
   - If `risk.mode = "risk_off"`:
     - Decision Engine should always yield FLAT except possibly for emergency position management.
5. **Multiple open positions (future extension)**
   - v1 assumes single net BTCUSDT position.
   - Architecture allows extension to multiple partial entries/exits, but core contract still refers to net decision.

---

## 10. Summary

The Decision Engine is a **deterministic, rule-based module** that:

- integrates **market structure, momentum, derivatives, ETF flows, liquidation maps and sentiment**,
- works under the constraints of a dedicated **Risk Manager**,
- emits a comprehensive **decision object** describing what to do, where to enter, where to exit, and with what size and leverage,
- is designed to be fully explainable and auditable:
  - reasons and risk_checks allow reconstructing every decision ex-post.

In combination with `RISK_MANAGER.md` and `EXECUTION_ENGINE.md`, this specification defines the full contract between analytics, risk and execution layers of the AI Trading Showdown Bot.
