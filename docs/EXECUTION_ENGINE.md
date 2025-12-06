# AI Trading Bot – EXECUTION_ENGINE.md (v2.0)

**Status:** Finalized — aligned with  
- PROJECT_OVERVIEW.md  
- DECISION_ENGINE.md v2.0  
- RISK_MANAGER.md v1.1  

---

## 1. Purpose

The **Execution Engine** is the module that transforms *decisions* into *actual orders and positions* on the exchange (Binance Futures / аналог).

Ключевые задачи:

- безопасное открытие/сопровождение/закрытие позиции,
- строгое соблюдение SL/TP/liq/trailing-логики,
- постоянный контроль за ордерами и позицией,
- устойчивость к ошибкам API/сети,
- полное восстановление управления после рестарта.

Execution Engine работает в **быстром цикле 1–3 секунды**, независимо от 5-минутного Analytics Loop.

---

## 2. Scope & Responsibilities

Execution Engine:

1. **НЕ принимает торговых решений по направлению**  
   - Он доверяет `decision.action` (long/short/flat).
   - Может **отказаться исполнять** (override to flat) только по причинам безопасности/риска.

2. **Управляет только исполнением:**
   - постановка входа (entry),
   - постановка/корректировка SL/TP,
   - частичные выходы,
   - trailing SL,
   - выходы по ликвидационным зонам,
   - аварийные выходы.

3. **Гарантирует:**
   - всегда есть действующий SL для открытой позиции,
   - SL **никогда не расширяется** (risk не увеличивается),
   - минимальный начальный SL ≥ **0.35%** выполняется,
   - RR ≥ 2.0 соблюдается (в связке с Decision Engine),
   - idempotent order handling (нет дублей).

---

## 3. Inputs & Dependencies

### 3.1 decision.json

Структура — см. `DECISION_ENGINE.md`. Ключевые поля:

- `symbol`
- `timestamp_iso`
- `action` (`"long" | "short" | "flat"`)
- `entry_zone` `[min, max]`
- `sl`, `tp1`, `tp2`
- `position_size_usdt`, `leverage`
- `risk_level`
- `confidence`
- `risk_checks`
- `position_management`:
  - `tp1_fraction` (обычно 0.5)
  - `enable_trailing` (true/false)
  - `trail_mode` ( `"structure_plus_liq"` )
  - `liq_tp_zone_id` (id сильного кластера)

### 3.2 Account state (from exchange / DB)

- текущая позиция по BTCUSDT:
  - side, size, entry price,
  - current SL / TP ордера.
- equity
- realized/unrealized PnL

### 3.3 Open orders

- список всех открытых ордеров по инструменту:
  - clientOrderId
  - type (LIMIT / MARKET / STOP / TAKE_PROFIT и т.д.)
  - side
  - price, qty
  - status

### 3.4 Config / Risk

- лимиты по leverage
- min order qty/notional
- настройки chase / market-entry / trailing
- max slippage etc.

---

## 4. Core Principles

1. **Никакой аналитики внутри Execution Engine**  
   Только исполнение и локальные проверки риска/безопасности.

2. **Idempotency**  
   Повторная отправка логически того же действия **не создаёт дубликатов**.

3. **SL & Safety First**  
   - любая открытая позиция всегда имеет SL,
   - при любой нештатной ситуации стратегия — “protect capital”.

4. **Full Recovery**  
   После рестарта Engine обязан:
   - обнаружить открытые позиции,
   - восстановить SL/TP,
   - синхронизировать DB и биржу,
   - продолжить управление позицией без «потери контроля».

---

## 5. Runtime Loop (1–3s)

High-level:

```python
def execution_loop():
    reconcile_on_startup()

    while True:
        decision = load_latest_decision()
        now = utc_now()

        position = get_exchange_position()
        open_orders = get_open_orders()

        if not decision or decision_is_stale(decision, now):
            handle_stale_decision(position, open_orders)
            sleep(LOOP_INTERVAL)
            continue

        if no_open_position(position):
            manage_entry(decision, position, open_orders)
        else:
            manage_position(decision, position, open_orders)

        sleep(LOOP_INTERVAL)
