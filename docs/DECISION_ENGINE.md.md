# **AI Trading Bot — DECISION_ENGINE.md (v2.0)**
### **Status:** Finalized — aligns with PROJECT_OVERVIEW, EXECUTION_ENGINE v1.1, RISK_MANAGER v1.1

---

# **1. Purpose**
Decision Engine — это детерминированный модуль, который принимает **единственное торговое решение** каждые 5 минут:

- **long**
- **short**
- **flat**

Он работает строго по данным:
- `btc_snapshot.json`
- `btc_flow.json`
- состоянию счёта и позиции
- правилам Risk Manager

И формирует:
- зону входа
- SL ≥ 0.35%
- TP1 / TP2 с RR ≥ 2.0
- liquidation-aware TP
- параметры позиции
- объяснение

Результат записывается в `decision.json` и таблицу `decisions`.

---

# **2. Inputs**

## **2.1 btc_snapshot.json**
Содержит:
- текущую цену
- свечи на 1m, 5m, 15m, 1h
- market structure (HH-HL / LH-LL / range)
- momentum state + score
- ATR
- session

## **2.2 btc_flow.json**
Содержит:
- funding
- OI / CVD
- crowd bias
- trap index
- liquidation zones (верх/низ)
- ETF summary
- warnings
- global risk_mode

## **2.3 Account state**
- equity
- текущая позиция (side, size, entry, SL/TP)
- дневной/недельный PnL & DD
- количество сделок за день

## **2.4 Risk Manager configuration**
- risk_per_trade
- SL/TP правила
- max trades per day
- дневной/недельный DD лимиты
- session rules
- leverage caps

---

# **3. Outputs — decision.json**
Формат:
```json
{
  "symbol": "BTCUSDT",
  "timestamp_iso": "2025-12-05T10:05:00Z",

  "action": "long",                       
  "reason": "trend_up_etf_support_liq_below",

  "entry_zone": [90700, 90900],
  "sl": 90380,
  "tp1": 91600,
  "tp2": 92900,

  "risk_level": 2,
  "position_size_usdt": 1200,
  "leverage": 3,

  "confidence": 0.74,

  "risk_checks": {
    "daily_dd_ok": true,
    "weekly_dd_ok": true,
    "max_trades_per_day_ok": true,
    "session_ok": true,
    "no_major_news": true
  },

  "position_management": {
    "tp1_fraction": 0.5,
    "enable_trailing": true,
    "trail_mode": "structure_plus_liq",
    "liq_tp_zone_id": "cluster_1"
  }
}
```

---

# **4. Decision Cycle (5-minute loop)**

1. Загрузка snapshot + flow + account_state
2. Оценка **LONG** кандидата
3. Оценка **SHORT** кандидата
4. Сравнение и выбор направления
5. Risk Manager overrides
6. Расчёт entry_zone, SL, TP1/TP2
7. Проверка RR ≥ 2.0
8. Формирование position management блока
9. Формирование confidence
10. Запись decision.json

---

# **5. Directional Logic**

## **5.1 LONG — условия**
- Market structure 5m/15m: HH-HL или range
- Momentum 5m: impulse_up или fading_up, score ≥ 0.55
- Derivatives: funding умеренный, OI растёт с ценой, нет отрицательной дивергенции CVD
- ETF inflows ≥ 0 или bullish signal
- Liquidations: сильные short-кластеры снизу
- Crowd/trap: толпа шортит → сигнал вверх
- Sentiment не негативный
- Нет critical warnings

Если ≥70% условий соблюдены → кандидат LONG.

## **5.2 SHORT — условия**
Зеркально LONG:
- структура LL-LH
- импульс вниз
- funding завышен
- long-кластеры сверху
- толпа в лонге

## **5.3 FLAT — условия**
- сигналы конфликтуют
- structure = range на всех TF
- momentum слабый
- RR < 2
- risk_checks нарушены
- объём сделок превышен
- high-risk режим

---

# **6. Position Management v1.1 (жёсткие правила)**
Это ключевой раздел переработанной версии.

## **6.1 Stop Loss (SL)**
### Правило №1 — SL ≥ **0.35%** от входа
Если вычисленный SL меньше → устанавливаем 0.35%.

### Правило №2 — SL никогда не увеличивается после входа

## **6.2 Risk-Reward Ratio (RR)**
Обязательное условие:
- **TP1 / SL ≥ 2.0**
- иначе сделка автоматически = FLAT

## **6.3 TP1 / TP2**
- TP1 — фиксированная цель или ближайший ликвидационный кластер
- TP1 закрывает 50% позиции
- TP2 — более дальний кластер или структура, но RR ≥ 2.0 обязательно

## **6.4 Liquidation-aware Take Profit**
Decision Engine выбирает ключевой кластер ликвидаций:

```json
"liq_tp_zone_id": "cluster_1"
```

и формирует TP по направлению сделки.

Если кластер усилился в следующем snapshot → TP корректируется.

## **6.5 Trailing Mode — structure_plus_liq**
После TP1 trailing активируется:
- SL движется только в сторону уменьшения риска
- базируется на swing-структуре
- дополнительно ускоряется при приближении к ликвидационным кластерам

---

# **7. Risk Manager Integration**
Decision Engine обязан подчиняться:

- дневному и недельному DD
- max trades per day
- risk_mode:
  - risk_off → всегда FLAT
  - cautious → уменьшить риск_level
  - aggressive → только при сильных сигналах

Если любой critical check = false → action = flat.

---

# **8. Position Size & Leverage**
Используется формула:

```
risk_usdt = equity * risk_percent
sl_distance = abs(entry - sl)
position_size = risk_usdt / sl_distance
```

Ограничения:
- leverage ≤ max_leverage(risk_mode)
- position_size_usdt ограничивается max_notional

---

# **9. Pseudocode v2.0**

```python
def make_decision(snapshot, flow, account, risk_cfg):

    long_cand  = eval_long(snapshot, flow, account)
    short_cand = eval_short(snapshot, flow, account)

    action, direction_reason, dir_conf = resolve_direction(long_cand, short_cand)

    risk_checks = run_risk_checks(account, risk_cfg)
    if not all_critical_ok(risk_checks):
        return flat_decision(reason=f"risk_block:{direction_reason}")

    if action == "flat":
        return flat_decision(reason=direction_reason)

    entry_zone = compute_entry_zone(snapshot, flow, action)
    sl = compute_sl(snapshot, flow, action, entry_zone)
    sl = max(sl, entry_zone_mid * 0.0035)  # SL ≥ 0.35%

    tp1, tp2 = compute_tps_with_liq(snapshot, flow, action, entry_zone, sl)
    if not rr_ok(tp1, sl):
        return flat_decision(reason="rr_too_low")

    size, lev, risk_lvl = compute_position_size(account, sl, risk_cfg)

    pm = {
        "tp1_fraction": 0.5,
        "enable_trailing": True,
        "trail_mode": "structure_plus_liq",
        "liq_tp_zone_id": flow.strongest_cluster_id
    }

    return Decision(
        action=action,
        reason=direction_reason,
        entry_zone=entry_zone,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        position_size_usdt=size,
        leverage=lev,
        confidence=dir_conf,
        risk_level=risk_lvl,
        risk_checks=risk_checks,
        position_management=pm
    )
```

---

# **10. Summary**
Decision Engine v2.0 обеспечивает:

- полную детерминированность решений
- строгие правила SL ≥ 0.35%, RR ≥ 2.0
- TP, основанные на ликвидационных зонах
- встроенную логику trailing
- 100% согласованность с Risk Manager и Execution Engine

Это ядро торговой системы.

