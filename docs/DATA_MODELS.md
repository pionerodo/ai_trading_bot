# AI Trading Showdown Bot – Data Models (Snapshots, Flows, Decisions)

Version: 1.0
Status: Canonical JSON/DB contract for analytics, API and execution

---

## 1. Purpose

This document captures the **authoritative data models** for the analytics artefacts:

- `btc_snapshot` (latest: `data/btc_snapshot.json`, history: `snapshots` table),
- `btc_flow` (latest: `data/btc_flow.json`, history: `flows` table),
- `decision` (latest: `data/decision.json`, history: `decisions` table).

It lists **mandatory fields**, optional enrichments, and **relationships** between the artefacts so that:

- Dashboard / API expose consistent payloads,
- Decision Engine and Execution Engine work against identical contracts,
- DB schemas stay aligned with JSON snapshots.

---

## 2. `btc_snapshot` model

### 2.1 Required fields

| Field | Type | Description |
| --- | --- | --- |
| `symbol` | string | Trading pair, e.g. `"BTCUSDT"`. |
| `timestamp_iso` | string | ISO8601 UTC timestamp. Aligns 1:1 with `flows.timestamp_iso` and `decisions.timestamp_iso`. |
| `timestamp_ms` | integer | Unix epoch milliseconds (helps ordering). |
| `price` | number | Last or mid-market price. |
| `candles` | object | Map of TF → `{o,h,l,c,v}`. **At least** `tf_1m`, `tf_5m`, `tf_15m`, `tf_1h` are expected. |

### 2.2 Optional/derived blocks

- `market_structure` (object): per-TF regime (`"HH-HL"`, `"LL-LH"`, `"range"`, ...).
- `momentum` (object): per-TF `{state, score}` with `state ∈ {impulse_up, impulse_down, fading, choppy, neutral}` and `score ∈ [0,1]`.
- `session` (object): `{current, time_utc, volatility_regime}`.

### 2.3 Persistence & relations

- **JSON path:** `data/btc_snapshot.json` (latest snapshot).
- **DB table:** `snapshots`:
  - `symbol`, `timestamp`, `price` columns mirror required fields.
  - JSON columns (`candles_json`, `market_structure_json`, `momentum_json`, `session_json`) preserve full fidelity.
- **Relations:**
  - `decisions.snapshot_id` → `snapshots.id` (FK-like link for provenance).
  - `flows.timestamp` and `decisions.timestamp` must match `snapshots.timestamp` produced in the same 5‑minute analytics cycle.

---

## 3. `btc_flow` model

### 3.1 Required fields

| Field | Type | Description |
| --- | --- | --- |
| `symbol` | string | `"BTCUSDT"`. |
| `timestamp_iso` | string | ISO8601 UTC; **must equal** the paired snapshot/decision timestamp. |
| `derivatives` | object | Contains `oi`, `funding`, `cvd` blocks with numeric values and directions. |
| `etp_summary` | object | Aggregated view from `btc_etp_flow.json` (`last_7d_total`, `last_3d_total`, `trend`, `signal`, `comment`). |
| `liquidation_zones` | object | Derived from `btc_liquidation_map.json` with `below_price`, `above_price`, `as_of`. |
| `crowd` | object | `{bias_score (0–1), bias_side, description}`. |
| `trap_index` | object | `{score (0–1), side, comment}`. |
| `news_sentiment` | object | Embedded copy of the latest `news_sentiment.json`. |
| `warnings` | array | List of `{type, severity, message}`. |
| `risk` | object | `{global_score (0–1), mode}` summarising overall caution/aggression. |

### 3.2 Persistence & relations

- **JSON path:** `data/btc_flow.json` (latest 5‑minute context).
- **DB table:** `flows`:
  - `symbol`, `timestamp`, `risk_global_score`, `risk_mode` mirror the primary attributes.
  - JSON columns (`derivatives_json`, `etp_summary_json`, `liquidation_json`, `crowd_json`, `trap_index_json`, `news_sentiment_json`, `warnings_json`) store the full objects.
- **Relations:**
  - `decisions.flow_id` → `flows.id` for provenance of each decision.
  - `flows.timestamp` is identical to the paired `snapshots.timestamp` and `decisions.timestamp`.
  - Dashboard/API endpoints `GET /api/flow` serve this object directly from JSON/DB.

---

## 4. `decision` model

### 4.1 Required fields

| Field | Type | Description |
| --- | --- | --- |
| `symbol` | string | `"BTCUSDT"`. |
| `timestamp_iso` | string | ISO8601 UTC, aligned with the source `snapshot`/`flow`. |
| `action` | string | One of `"long"`, `"short"`, `"flat"`. Mandatory. |
| `reason` | string | Short snake_case explanation of the chosen action. |
| `entry_zone` | array | `[min_price, max_price]` band for entries. Required even for `flat` (can repeat price). |
| `sl` | number | Stop-loss level. |
| `tp1` | number | First take-profit. |
| `tp2` | number | Second take-profit (nullable). |
| `risk_level` | integer | Discrete 1–5 risk level chosen by the engine. |
| `position_size_usdt` | number | Notional position size in USDT. |
| `leverage` | number | Target leverage capped by config/risk mode. |
| `confidence` | number | 0–1 combined score. |
| `risk_checks` | object | `{daily_dd_ok, weekly_dd_ok, max_trades_per_day_ok, session_ok, no_major_news}` booleans. |

### 4.2 Persistence & relations

- **JSON path:** `data/decision.json` (latest output of Decision Engine).
- **DB table:** `decisions`:
  - Columns map 1:1 to decision fields (`action`, `reason`, `entry_min_price`, `entry_max_price`, `sl_price`, `tp1_price`, `tp2_price`, `risk_level`, `position_size_usdt`, `leverage`, `confidence`, `risk_checks_json`).
  - Foreign-key-style links to analytics artefacts: `snapshot_id`, `flow_id`.
- **Relations:**
  - Downstream entities (`orders`, `trades`, `positions`) link back via `decision_id` for auditability.
  - API endpoints `GET /api/decision` and `GET /api/status` expose the latest row/JSON.

---

## 5. Cross-artifact consistency rules

1. **Timestamp alignment** – `snapshots.timestamp_iso == flows.timestamp_iso == decisions.timestamp_iso` for every 5‑minute cycle.
2. **Symbol locking** – all three artefacts must share the same `symbol` (`config.app.symbol`).
3. **ID provenance** – when persisting, store `decisions.snapshot_id` and `decisions.flow_id` so API consumers can trace inputs used for any trading action.
4. **Validation requirements**:
   - Required fields above must be present and type-correct; otherwise the cycle is rejected and surfaced as a dashboard warning.
   - Numeric ranges follow `DATA_PIPELINE.md` (`score` in `[0,1]`, `risk_level` in `1..5`, etc.).
5. **Regeneration contract** – each analytics loop overwrites the JSON snapshots while inserting the corresponding DB rows, keeping history in MariaDB but exposing the “latest” view to the API and Execution Engine.

These rules ensure that snapshots, flows and decisions stay **synchronised across JSON, DB, Dashboard API and live execution**.
