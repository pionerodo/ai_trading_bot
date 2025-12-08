# AI Trading Showdown Bot  
Autonomous BTCUSDT analytics & trading engine  
Version: 1.0 (Architecture Draft)

## 1. Overview

**AI Trading Showdown Bot** — это автономный торгово-аналитический контур, работающий на отдельном Python-приложении.  
Основная функция — анализ BTCUSDT, формирование торговых решений и исполнение сделок через Binance Futures.

Система использует комбинацию:

- рыночных данных Binance (свечи, объём, деривативы),
- ручных источников (ETF-потоки, ликвидационные зоны, sentiment),
- двухуровневого AI-ядра:
  - **Analysis Engine** — структурный, детерминированный анализ рынка,
  - **Decision Engine** — правила принятия решений + риск-менеджмент,
- **Execution Engine** — торговля, SL/TP, лимитные ордера, Reconciliation,
- **Dashboard** — ввод данных, мониторинг, диагностика.

Система полностью автономна и не привязана к сайтам cryptobavaro.online или capibaratrader.com.

---

## 2. High-Level Architecture

```
Data Collectors --> Analytics Engine --> Flow Aggregation --> Decision Engine --> Execution Engine --> Binance API
         ^                                                                                                  |
         |--------------------------------------------------------------------------------------------------|
```

### Основные модули:

1. **Data Collector**
   - Сбор свечей 1m/5m/15m/1h (Binance Futures)
   - Деривативы: OI, Funding, CVD, Basis
   - Запись в БД (MariaDB)

2. **Analytics Engine**
   - Генерация `btc_snapshot.json`
   - Выделение структуры рынка (HH/HL/LL/LH)
   - Импульс/затухание (momentum)
   - Сессии (Asia/EU/US)
   - Волатильность (ATR)

3. **Flow Engine**
   - Генерация `btc_flow.json`
   - Интеграция:
     - ETF-потоки (`btc_etp_flow.json`)
     - Ликвидационные зоны (`btc_liquidation_map.json`)
     - Manual sentiment (dashboard)
     - Derivatives context (OI/Funding/CVD)
   - Расчёт:
     - crowd_bias
     - trap_index
     - warnings
     - risk.global_score

4. **Decision Engine**
   - Детализированные правила открытия/закрытия позиций
   - Расчёт SL/TP по ATR
   - Размер позиции через risk-per-trade
   - Ограничение DD (day/week)
   - Конфликт сигналов → FLAT режим

5. **Execution Engine**
   - Реализация торговых решений в реальном времени
   - Separate loop (1–3 сек)
   - Limit chase logic
   - Emergency market fills (при строгих условиях)
   - Full Reconciliation при рестарте:
     - сверка позиций Binance <-> БД
     - восстановление SL/TP при потере ордеров
   - Логи + Telegram уведомления (ERROR / RISK / ORDERS)

6. **Dashboard**
   - Ввод sentiment
   - Ввод ETF JSON
   - Ввод liquidation zones JSON
   - Просмотр текущего состояния бота
   - Логи и диагностика

---

## 3. File Structure

```
ai_trading_bot/
│
├── config/
│   ├── config.yaml                 # Основной конфиг
│   └── config.local.yaml           # Локальный (в .gitignore)
│
├── data/
│   ├── btc_snapshot.json           # Последний срез рынка
│   ├── btc_flow.json               # Агрегированный поток/толпа/риск
│   ├── btc_etp_flow.json           # Ежедневные ETF-потоки
│   ├── btc_liquidation_map.json    # Ликвидационные зоны
│   └── news_sentiment.json         # Ввод с дашборда
│
├── logs/                           # Runtime логи (в .gitignore)
│
├── src/
│   ├── data_collector/
│   │   ├── candles_collector.py
│   │   ├── derivatives_collector.py
│   │   └── db_utils.py
│   │
│   ├── analytics_engine/
│   │   ├── generate_btc_snapshot.py
│   │   ├── generate_btc_flow.py
│   │   └── decision_engine.py
│   │
│   ├── execution_engine/
│   │   ├── binance_client.py
│   │   ├── execution_loop.py
│   │   └── reconciliation.py
│   │
│   └── dashboard/
│       ├── api.py
│       └── views.py
│
└── static/
```

---

## Environment variables

Приложение проверяет наличие обязательных переменных окружения при запуске
подключений к БД. Укажите их в `.env` (см. `.env.example`) или в окружении
процесса:

- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — подключение к MariaDB/MySQL.
- `BINANCE_API_KEY`, `BINANCE_API_SECRET` — нужны только при работе с Binance.
- Дополнительно можно задать `BINANCE_TESTNET` и `BINANCE_BASE_ASSET`.

Если какие-то значения не заданы, код завершится с ошибкой при попытке
подключения. YAML-конфиг (`config/config.yaml`) может содержать бэкап-значения,
но приоритет всегда у переменных окружения.

---

## 4. JSON Data Pipeline

### 4.1 `btc_snapshot.json`
Генерируется каждые 5 минут.  
Содержит:

- цену,
- свечи,
- структуру рынка,
- импульс,
- ATR,
- режим сессии.

### 4.2 `btc_flow.json`
Агрегирует:

- derivatives,
- ETF summary,
- liquidation zones,
- sentiment,
- crowd/trap/warnings,
- общий риск.

### 4.3 `decision.json`
Пример структуры:

```json
{
  "action": "long",
  "entry_zone": [90700, 90900],
  "sl": 89800,
  "tp1": 92200,
  "tp2": 93500,
  "risk_level": 3,
  "position_size_usdt": 1000,
  "confidence": 0.76,
  "reason": "trend_up_multi_tf_with_etf_support"
}
```

---

## 5. Decision Logic Summary

### Long
- рынок в HH-HL (5m/15m)
- импульс вверх
- приемлемый funding
- OI не падает
- ликвидации снизу
- ETF-поддержка
- risk.global_score OK

### Short
Зеркально.

### Flat
- конфликт сигналов,
- high-risk,
- превышен DD,
- warnings.

---

## 6. Execution Engine

### Execution loop
- работает 1–3 сек
- управление лимитками
- fail-safe market entry
- слежение за SL/TP

### Reconciliation
При старте:

- сверка позиций Binance <-> БД,
- восстановление недостающих ордеров,
- логирование ошибок,
- уведомления в Telegram.

---

## 7. Database (MariaDB)

Исторические таблицы:

- candles  
- derivatives  
- etp_flows  
- liquidation_zones_history  
- news_sentiment_history  
- snapshots  
- flows  
- decisions  
- orders  
- trades  
- equity_curve  
- logs  

JSON-файлы используются как последние снапшоты.

---

## 8. Backtesting Engine (v1.1)

Модуль симуляции:

- подаёт исторические данные,
- прогоняет Analytics → Flow → Decision,
- симулирует исполнение сделок,
- строит equity.

---

## 9. Deployment

### Dev:

```
python src/data_collector/candles_collector.py
python src/analytics_engine/generate_btc_snapshot.py
python src/analytics_engine/generate_btc_flow.py
python src/execution_engine/execution_loop.py
```

### Prod stack:
- Gunicorn/Uvicorn
- Supervisor/systemd
- Nginx reverse proxy

---

## 10. Development

### Environment

```bash
pip install -r requirements-dev.txt
```

### Linting

```bash
ruff check src scripts
flake8 src scripts
```

### Type Checking

```bash
mypy src scripts
```

### Tests

```bash
pytest
```

---

## 11. Roadmap

### v1.0
✔ analytics  
✔ decision engine  
✔ execution loop  
✔ reconciliation  
✔ ETF/liquidations integration  

### v1.1
⬜ backtester  
⬜ улучшенные SL/TP  
⬜ расширенный risk engine  

### v2.0
⬜ multi-asset  
⬜ AI-advisor  
⬜ ML meta-layer  

---

## 12. License
Private project — all rights reserved.

## 13. Maintainer
**pionerodo**
GitHub: https://github.com/pionerodo
