# AI Trading Showdown Bot – Input Formats & Manual Workflows

Version: 1.0  
Status: Aligned with DATA_PIPELINE and ARCHITECTURE

---

## 1. Purpose

This document describes **all external inputs**, their formats and workflows:

1. JSON files that the user prepares (often with help of LLM):
   - `btc_etp_flow.json`
   - `btc_liquidation_map.json`
2. Manual sentiment input:
   - `news_sentiment.json`
3. Interaction via **Dashboard**:
   - forms, upload areas, validation rules.

The goal is to make sure that:

- the user always knows **что и как заполнять**,
- the system always receives **валидные и предсказуемые данные**,
- ошибки при ручном вводе данных не ломают весь пайплайн.

---

## 2. Общий контракт для всех входов

### 2.1 Общие требования

- Все входные JSON-файлы должны:
  - быть полностью валидным JSON (без комментариев),
  - иметь корректную кодировку UTF-8,
  - использовать **точный набор полей**, описанный ниже.

- Даты и время:
  - формат дат: `YYYY-MM-DD`,
  - формат datetime: ISO8601 с `Z`, например: `"2025-11-28T00:00:00Z"`.

- Числа:
  - без тысячных разделителей (никаких `1,000,000` → только `1000000`),
  - десятичная точка — только `.`.

### 2.2 Валидация и поведение при ошибках

При загрузке / сохранении:

- Если JSON:
  - **не парсится** → запись отклоняется, в Dashboard показывается ошибка.
  - имеет **отсутствующие обязательные поля** → отклоняется.
  - имеет **поля неверного типа** (строка вместо числа и т.п.) → отклоняется.
- Ошибка не должна ломать Analytics Loop:
  - текущий цикл может:
    - использовать **последнюю валидную версию**,
    - либо отключить соответствующий модуль (`ETF`, `liq`, `sentiment`) и добавить `warning` в `btc_flow.json`.

Все ошибки логируются и отображаются в Dashboard.

---

## 3. `btc_etp_flow.json` – Ежедневные ETF-потоки

### 3.1 Где используется

- Основной источник агрегированного блока `etp_summary` в `btc_flow.json`.
- Влияет на:
  - оценку глобального настроения крупных игроков,
  - режим Risk Manager и Decision Engine.

### 3.2 Кто и как готовит

**Workflow:**

1. Пользователь берёт скриншот с сайта `https://farside.co.uk/btc/`.
2. Отправляет этот скриншот в отдельный чат с LLM (по заранее подготовленному промту).
3. Получает корректный JSON `btc_etp_flow.json` и:
   - либо копирует его в файл на сервере,
   - либо вставляет через форму в Dashboard для ETF.

Скрипт/форма Dashboard должна сохранять JSON в:

```text
data/btc_etp_flow.json
```

### 3.3 Формат файла

Пример:

```json
{
  "symbol": "BTC",
  "history": [
    { "date": "2025-11-21", "net_flow_usd": -120000000.0 },
    { "date": "2025-11-22", "net_flow_usd": -80000000.0 },
    { "date": "2025-11-23", "net_flow_usd": -50000000.0 },
    { "date": "2025-11-24", "net_flow_usd": -20000000.0 },
    { "date": "2025-11-25", "net_flow_usd": 5000000.0 },
    { "date": "2025-11-26", "net_flow_usd": 15000000.0 },
    { "date": "2025-11-27", "net_flow_usd": 25000000.0 }
  ],
  "summary": {
    "last_7d_total": -235000000.0,
    "last_3d_total": 45000000.0,
    "trend": "recovering",
    "signal": "bullish_reversal",
    "comment": "После серии оттоков появились 3 дня притоков"
  },
  "as_of": "2025-11-28T00:00:00Z"
}
```

#### Обязательные поля

- `symbol` (string): `"BTC"`.
- `history` (array of objects):
  - `date` (string, `YYYY-MM-DD`),
  - `net_flow_usd` (number) — **в USD**, НЕ в миллионах.
- `summary` (object):
  - `last_7d_total` (number),
  - `last_3d_total` (number),
  - `trend` (string),
  - `signal` (string),
  - `comment` (string).
- `as_of` (string, datetime).

#### Правила валидации

- `history`:
  - даты уникальны,
  - отсортированы по возрастанию,
  - без пропусков внутри последних N дней (опционально).
- `net_flow_usd`:
  - может быть отрицательным (отток) или положительным (приток),
  - 0 разрешен.
- `summary`:
  - должна быть **консистентна** с `history` (суммы можно пересчитать и сравнить).
- `as_of`:
  - должен быть >= последней даты из `history`.

---

## 4. `btc_liquidation_map.json` – Карта ликвидаций

> В коде теперь используются промежуточные файлы `btc_liq_snapshot.json`
> (последний снимок) и `btc_liq_map.json` (история). Скрипт
> `src/data_collector/liq_map_updater.py` принимает человеческий
> `btc_liquidation_map.json` и конвертирует его в эти рабочие форматы.
> Следующий блок описывает исходный формат, который по-прежнему остаётся
> «единой точкой входа» для данных ликвидаций.

### 4.1 Где используется

- Формирует блок `liquidation_zones` внутри `btc_flow.json`.
- Важен для:

  - определения “магнитов” цены,
  - оценки риска ложных пробоев,
  - сценариев squeeze против толпы.

### 4.2 Кто и как готовит

**Workflow:**

1. Пользователь делает скриншот карты ликвидаций (Coinglass/Hyperliquid) целиком.
2. Отправляет в чат с LLM по специальному промту-парсеру.
3. Получает JSON `btc_liquidation_map.json`.
4. Загружает его через Dashboard или сохраняет в `data/btc_liquidation_map.json`.

### 4.3 Формат файла

Пример:

```json
{
  "symbol": "BTC",
  "as_of": "2025-11-28T12:00:00Z",
  "current_price": 90850.0,
  "below_price": [
    {
      "price": 86000.0,
      "zone": [85500.0, 86500.0],
      "side": "short",
      "strength": 0.8,
      "comment": "крупный кластер шортов снизу"
    }
  ],
  "above_price": [
    {
      "price": 95000.0,
      "zone": [94500.0, 95500.0],
      "side": "long",
      "strength": 0.9,
      "comment": "главный магнит ликвидаций лонгов сверху"
    }
  ]
}
```

#### Обязательные поля

- `symbol` (string) – `"BTC"`.
- `as_of` (string, datetime).
- `current_price` (number).
- `below_price` (array of zone objects).
- `above_price` (array of zone objects).

**Zone object:**

- `price` (number) – центр кластера.
- `zone` (array `[min, max]`).
- `side` (string):
  - `"short"` – зона ликвидаций шортов,
  - `"long"` – зона ликвидаций лонгов.
- `strength` (number, 0–1) – нормированная сила.
- `comment` (string, optional).

#### Правила валидации

- `zone[0] <= price <= zone[1]`.
- `strength` ∈ [0, 1].
- Для `below_price` кластеры **обычно** ниже `current_price`.
- Для `above_price` — выше (не строгое правило, но можно предупреждать).

Если карта старая (`as_of` сильно отстаёт от текущего времени) → Analytics Engine должен:

- выставить warning,
- снизить вес ликвидаций в общем risk-score.

---

## 5. `news_sentiment.json` – Ручной сентимент

### 5.1 Где используется

- Входит в `btc_flow.json` как `news_sentiment`.
- Участвует в:

  - Risk Manager,
  - Decision Engine (коррекция confidence).

### 5.2 Кто и как готовит

Через Dashboard:

- форма с полями:
  - `score` (слайдер/радиокнопки: -2, -1, 0, +1, +2),
  - `label` (автоопределяется по score),
  - `comment` (текстовое поле).

Сохранение в `data/news_sentiment.json` и в таблицу `news_sentiment_history`.

### 5.3 Формат файла

```json
{
  "as_of": "2025-11-28T10:00:00Z",
  "score": 1,
  "label": "bullish",
  "comment": "Позитивные новости по ETF и макро"
}
```

#### Поля

- `as_of` (string, datetime).
- `score` (int или небольшой float) – обычно -2..+2.
- `label` (string):
  - `"bearish"`, `"neutral"`, `"bullish"` (можно расширить).
- `comment` (string).

#### Правила валидации

- `label` должен соответствовать `score` (простая мапа в коде).
- Если `as_of` слишком старый (например, > 48 часов назад), Analytics Engine ставит warning и снижает вес сентимента.

---

## 6. Работа через Dashboard

### 6.1 Основные экраны

1. **ETF Flows**
   - Текстовое поле/textarea для вставки JSON.
   - Кнопка “Validate & Save”.
   - При успехе:
     - JSON сохраняется в `data/btc_etp_flow.json`.
     - создаётся запись в `etp_flows`.
   - При ошибке:
     - отображается список найденных проблем.

2. **Liquidation Map**
   - Аналогично ETF:
     - окно вставки JSON,
     - валидация,
     - сохранение в `data/btc_liquidation_map.json` и в `liquidation_zones_history`.

3. **Sentiment**
   - UI-форма:
     - выбор `score`,
     - авто-лейбл,
     - поле `comment`.
   - Сохранение:
     - `data/news_sentiment.json`,
     - `news_sentiment_history`.

4. **JSON Previews**
   - Панель, где можно видеть:
     - текущий `btc_snapshot.json`,
     - `btc_flow.json`,
     - `decision.json`,
     - ETF/liqs/sentiment JSON.
   - Удобно для отладки и понимания состояния.

---

## 7. CLI/Server-side Editing (при отсутствии Dashboard)

До того как Dashboard будет реализован (или в аварийном режиме), можно редактировать JSON:

- по SSH,
- в любом текстовом редакторе (nano, vim),
- строго по описанным форматам.

Файлы расположены в:

```text
/path/to/project/data/
    btc_snapshot.json        (генерируется автоматически)
    btc_flow.json            (генерируется автоматически)
    btc_etp_flow.json        (ручной ввод)
    btc_liquidation_map.json (ручной ввод)
    news_sentiment.json      (ручной/через форму ввод)
    decision.json            (генерируется автоматически)
```

Важно:

- не переименовывать файлы,
- не добавлять туда комментарии/лишние поля.

---

## 8. Обработка ошибок и предупреждений

Примеры ситуаций:

1. **Не валидный JSON в ETF**
   - Analytics Engine:
     - пишет в лог ERROR,
     - добавляет warning в `btc_flow.json`:
       - тип `"etf_data_invalid"`.
     - использует **нулевой ETF-вклад** в risk & decision.

2. **Старая карта ликвидаций**
   - Если `as_of` далеко в прошлом:
     - warning `"liq_data_stale"`,
     - снижает `liq_score`.

3. **Отсутствие sentiment**
   - Если нет валидного `news_sentiment.json`:
     - трактуем как `score = 0`, `label = "neutral"`,
     - но добавляем warning `"sentiment_missing"`.

Все предупреждения выводятся:

- в `warnings` внутри `btc_flow.json`,
- в Dashboard (раздел Diagnostics),
- в логах.

---

## 9. Примеры “минимально валидных” версий

### 9.1 Минимальный `btc_etp_flow.json`

```json
{
  "symbol": "BTC",
  "history": [
    { "date": "2025-11-26", "net_flow_usd": 15000000.0 }
  ],
  "summary": {
    "last_7d_total": 15000000.0,
    "last_3d_total": 15000000.0,
    "trend": "accumulating",
    "signal": "bullish",
    "comment": "Однодневный приток, сохраняем осторожность"
  },
  "as_of": "2025-11-27T00:00:00Z"
}
```

### 9.2 Минимальный `btc_liquidation_map.json`

```json
{
  "symbol": "BTC",
  "as_of": "2025-11-28T12:00:00Z",
  "current_price": 90850.0,
  "below_price": [],
  "above_price": []
}
```

(При пустых массивах блок liq просто не влияет на решения, но не ломает систему.)

### 9.3 Минимальный `news_sentiment.json`

```json
{
  "as_of": "2025-11-28T10:00:00Z",
  "score": 0,
  "label": "neutral",
  "comment": ""
}
```

---

## 10. Резюме

`INPUT_FORMATS.md` описывает:

- **что именно пользователь должен делать руками**,  
- **какой формат JSON обязателен**,  
- **как Dashboard помогает избежать ошибок**,  
- **как система реагирует на некорректные или устаревшие данные**.

Вместе с:

- `DATA_PIPELINE.md`  
- `ARCHITECTURE.md`  
- `DECISION_ENGINE.md`  
- `RISK_MANAGER.md`

этот документ закрывает все вопросы по входящим данным для AI Trading Showdown Bot.
