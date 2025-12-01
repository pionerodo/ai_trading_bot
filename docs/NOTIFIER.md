# AI Trading Showdown Bot – Notifier & Alerting Specification

Version: 1.0  
Status: Integrated with ARCHITECTURE, EXECUTION_ENGINE, RISK_MANAGER, DATABASE_SCHEMA, DASHBOARD, MILESTONES.

---

## 1. Purpose

The **Notifier** is the alerting layer of the system.

It:

- listens to important events (errors, DD, anomalies),
- sends **Telegram** notifications to the operator,
- writes all alerts into the **MariaDB `notifications` table**,
- helps detect and react to critical problems in real time.

Notifier **не принимает торговых решений** и **не управляет ордерами**.  
Он только информирует.

---

## 2. Transports

### 2.1 Telegram

- Dedicated Telegram Bot (Bot API token in config).
- One or several chat IDs (operator / tech channel).
- All critical events duplicated в этот канал.

### 2.2 MariaDB `notifications` Table

All alerts записываются в таблицу:

- для аудита,
- для последующего анализа,
- для отображения в Dashboard (раздел Logs & Diagnostics).

Схема таблицы описана в `DATABASE_SCHEMA.md`.

---

## 3. Events & Triggers

Notifier получает события из:

- **Execution Engine**
- **Risk Manager**
- **Reconciliation Engine**
- **Analytics / Flow Engine**
- **System Health / Scheduler**

### 3.1 Risk-related events

- **Daily DD breach**
  - `risk.daily_dd_ok` → false
  - Переход системы в `risk_off`.
- **Weekly DD breach**
  - `risk.weekly_dd_ok` → false.
- **Risk mode change**
  - from `neutral` → `risk_off`  
  - from `aggressive` → `cautious` (после аномалий).

### 3.2 Execution events

- Order placement failure (после нескольких retry).
- Невозможность выставить SL.
- Repeated API errors (rate limit, invalid signature, etc.).
- Forced **market entry** when limit entry не успел исполниться.
- SL/TP recreation after missing order обнаружен.

### 3.3 Reconciliation events

- Orphan position найден (позиция есть на Binance, в БД её нет).
- Phantom position (в БД есть OPEN, на бирже позиция = 0).
- Missing SL / TP detected.
- Orphan orders (live orders без связи с decisions/positions).

### 3.4 Analytics & Data Quality

- ETF data invalid (невалидный JSON / пустой history).
- ETF data stale (последняя дата слишком старая).
- Liquidation map stale.
- Sentiment missing / stale.
- Snapshot/flow timestamps сильно отстают (проблема с scheduler).

### 3.5 System Health

- Execution loop не отправлял heartbeat дольше N секунд.
- Analytics loop остановился.
- Ошибка подключения к БД.

---

## 4. Alert Payload

Общий формат сообщения в Telegram:

```text
[LEVEL] [SOURCE] [CODE]

Time: 2025-11-28T12:34:56Z
Details: <читаемое описание события>
Context: <основные поля (symbol, price, side, decision_id, order_id, risk_mode)>

Action: <что рекомендуется сделать оператору>
```

Пример:

```text
[CRITICAL] [EXECUTION] [MISSING_SL]

Time: 2025-11-28T12:34:56Z
Details: Position BTCUSDT LONG 0.5 BTC detected WITHOUT SL on Binance.
Context: position_id=123, entry_price=90500, equity=10000, risk_mode=neutral

Action: SL recreated automatically at 89200. Check recon logs on dashboard.
```

---

## 5. Notification Levels

Уровни:

- `INFO` – базовые события (start/stop, mode change).
- `WARNING` – потенциальные проблемы, но система продолжает работать (stale ETF, sentiment missing).
- `ERROR` – важные ошибки, но система ещё может торговать.
- `CRITICAL` – блокирующие проблемы:
  - DD breach,
  - отсутствующий SL,
  - невозможность выставить ордер.

Настройка: можно фильтровать, какие уровни реально отправляются в Telegram (обычно WARNING+).

---

## 6. Database Schema Integration

Таблица:

- `notifications` – все события с уровнем, источником, payload, статусом доставки.

Подробнее см. `DATABASE_SCHEMA.md`.

Notifier:

- пишет запись в таблицу **сначала**,  
- затем пытается отправить в Telegram,
- обновляет статус (sent / failed / retry).

---

## 7. Integration Points

### 7.1 Execution Engine

Вызовы Notifier при:

- критических ошибках Binance API;
- невозможности выставить SL;
- fallback на рыночный вход;
- обнаружении partial fill аномалий;
- успешном закрытии позиции (по желанию – как INFO).

### 7.2 Risk Manager

Вызовы при:

- входе в `risk_off`;
- достижении дневного/недельного DD-лимита;
- резком снижении global risk score.

### 7.3 Reconciliation Engine

Вызовы при:

- orphan / phantom positions;
- missing SL/TP;
- orphan orders.

### 7.4 Scheduler / Healthcheck

- watchdog-процессы, которые проверяют “жив ли” Execution / Analytics loop.

---

## 8. Anti-Spam & Throttling

Чтобы Telegram не превратился в «белый шум»:

- одинаковые события за короткий интервал агрегируются;
- менее важные предупреждения могут группироваться в один digest (например, раз в 10 минут);
- лимит на количество сообщений в минуту.

При этом **CRITICAL** события всегда проходят немедленно.

---

## 9. Dashboard Integration

В Dashboard:

- отдельный раздел “Alerts / Notifications”:
  - список последних событий (таблица из `notifications`);
  - фильтр по уровню/источнику/коду;
  - статус доставки (sent/failed/retry);
  - возможность отметить уведомление как “прочитанное” (опционально).

---

## 10. Configuration

Основные настройки Notifier:

- `telegram_bot_token`
- `telegram_chat_ids` (список)
- `min_level_for_telegram` (например, `WARNING`)
- `retry_attempts`
- `retry_delay`
- включение/выключение отдельных типов событий.

Хранятся в `config/`.

---

## 11. Summary

Notifier – это:

- **централизованный слой оповещения**,
- используемый всеми критическими компонентами (Risk, Execution, Reconciliation, Analytics),
- с двумя каналами:
  - **Telegram** — оперативная реакция,
  - **MariaDB (`notifications`)** — долговременный журнал событий.

Он повышает надёжность системы и позволяет быстро понимать, что происходит с ботом в реальном времени.
