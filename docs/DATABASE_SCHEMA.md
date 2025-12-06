# AI Trading Bot – DATABASE_SCHEMA.md (v2.0, synced with live DB)

**Status:** This document describes the *actual* MariaDB schema of the `ai_trading_bot` database as of the latest migration. All `CREATE TABLE` definitions below are taken directly from the live DB dump.**

---

## 1. General Notes

- DB engine: MariaDB / MySQL (InnoDB tables).
- Charset: `utf8mb4` (для части таблиц — `utf8mb3`, как в реальной БД).
- All timestamps are stored in UTC (either `DATETIME`, `TIMESTAMP` or `BIGINT` in ms).
- JSON-поля храним как `LONGTEXT` + `CHECK (json_valid(...))`, либо как сырой текст.
- Логика и назначение таблиц описаны в остальных документах ТЗ (DATA_PIPELINE.md, DECISION_ENGINE.md, EXECUTION_ENGINE.md, RISK_MANAGER.md).

---

## 2. Tables Overview

Ниже перечислены все таблицы, существующие в БД `ai_trading_bot`:

- `bot_state`
- `candles`
- `decisions`
- `derivatives`
- `equity_curve`
- `etp_flows`
- `executions`
- `flows`
- `liquidation_zones`
- `logs`
- `market_flow`
- `news_sentiment_history`
- `notifications`
- `orders`
- `positions`
- `reconciliation_events`
- `risk_events`
- `snapshots`
- `trades`

Ниже для каждой таблицы приведён её фактический `CREATE TABLE` из дампа.

---

## 3. Таблица `bot_state`

```sql
CREATE TABLE `bot_state` (
  `id` int(11) NOT NULL DEFAULT 1,
  `position` varchar(10) NOT NULL DEFAULT 'NONE',
  `entry_price` decimal(20,8) DEFAULT NULL,
  `entry_time` bigint(20) DEFAULT NULL,
  `qty` decimal(20,8) DEFAULT NULL,
  `stop_loss` decimal(20,8) DEFAULT NULL,
  `take_profit` decimal(20,8) DEFAULT NULL,
  `equity` decimal(20,8) DEFAULT 10000.00000000,
  `updated_at` bigint(20) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

4. Таблица candles

CREATE TABLE `candles` (
  `id` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `timeframe` varchar(10) NOT NULL,
  `open_time` bigint(20) NOT NULL,
  `open` decimal(20,8) NOT NULL,
  `high` decimal(20,8) NOT NULL,
  `low` decimal(20,8) NOT NULL,
  `close` decimal(20,8) NOT NULL,
  `volume` decimal(20,8) NOT NULL,
  `close_time` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_candle` (`symbol`,`timeframe`,`open_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

5. Таблица decisions

CREATE TABLE `decisions` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `created_at_utc` datetime DEFAULT NULL,
  `symbol` varchar(20) NOT NULL,
  `timeframe` varchar(16) NOT NULL DEFAULT '5m',
  `action` varchar(10) NOT NULL,
  `confidence` float NOT NULL,
  `reason` text DEFAULT NULL,
  `entry_min` decimal(20,8) DEFAULT NULL,
  `entry_max` decimal(20,8) DEFAULT NULL,
  `sl` decimal(20,8) DEFAULT NULL,
  `tp1` decimal(20,8) DEFAULT NULL,
  `tp2` decimal(20,8) DEFAULT NULL,
  `sl_pct` decimal(10,6) DEFAULT NULL,
  `tp1_rr` decimal(10,4) DEFAULT NULL,
  `tp2_rr` decimal(10,4) DEFAULT NULL,
  `position_size_usdt` decimal(20,8) DEFAULT NULL,
  `leverage` decimal(10,4) DEFAULT NULL,
  `risk_level` tinyint(4) DEFAULT NULL,
  `risk_mode` enum('risk_off','cautious','neutral','aggressive') NOT NULL DEFAULT 'neutral',
  `daily_dd_ok` tinyint(1) NOT NULL DEFAULT 1,
  `weekly_dd_ok` tinyint(1) NOT NULL DEFAULT 1,
  `max_trades_per_day_ok` tinyint(1) NOT NULL DEFAULT 1,
  `session_ok` tinyint(1) NOT NULL DEFAULT 1,
  `no_major_news` tinyint(1) NOT NULL DEFAULT 1,
  `liquidation_ok` tinyint(1) NOT NULL DEFAULT 1,
  `etf_ok` tinyint(1) NOT NULL DEFAULT 1,
  `liq_tp_zone_id` varchar(64) DEFAULT NULL,
  `position_management_json` longtext DEFAULT NULL,
  `snapshot_ref_id` bigint(20) UNSIGNED DEFAULT NULL,
  `flow_ref_id` bigint(20) UNSIGNED DEFAULT NULL,
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`)),
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_decision` (`symbol`,`timestamp_ms`),
  KEY `idx_decisions_symbol_time` (`symbol`,`created_at_utc`),
  KEY `idx_decisions_action` (`symbol`,`action`,`created_at_utc`),
  KEY `idx_decisions_risk_mode` (`risk_mode`,`created_at_utc`),
  KEY `idx_decisions_snapshot` (`snapshot_ref_id`),
  KEY `idx_decisions_flow` (`flow_ref_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

6. Таблица derivatives

CREATE TABLE `derivatives` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `funding_rate` double DEFAULT NULL,
  `open_interest` double DEFAULT NULL,
  `long_short_ratio` double DEFAULT NULL,
  `basis` double DEFAULT NULL,
  `oi_change_1h` double DEFAULT NULL,
  `oi_change_4h` double DEFAULT NULL,
  `volume_24h` double DEFAULT NULL,
  `taker_buy_ratio` double DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_derivative_record` (`symbol`,`timestamp_ms`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

7. Таблица equity_curve

CREATE TABLE `equity_curve` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `captured_at_utc` datetime NOT NULL,
  `equity_usdt` decimal(20,8) NOT NULL,
  `balance_usdt` decimal(20,8) NOT NULL,
  `open_pnl_usdt` decimal(20,8) NOT NULL,
  `closed_pnl_usdt` decimal(20,8) NOT NULL,
  `daily_dd_pct` decimal(10,4) NOT NULL,
  `weekly_dd_pct` decimal(10,4) NOT NULL,
  `risk_mode` enum('risk_off','cautious','neutral','aggressive') NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_equity_time` (`captured_at_utc`),
  KEY `idx_equity_mode` (`risk_mode`,`captured_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

8. Таблица etp_flows

CREATE TABLE `etp_flows` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `date_utc` date NOT NULL,
  `source` varchar(64) NOT NULL,
  `payload_json` longtext NOT NULL,
  `total_net_flow_usd` decimal(20,2) DEFAULT NULL,
  `notes` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_etp_symbol_date_source` (`symbol`,`date_utc`,`source`),
  KEY `idx_etp_date` (`date_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

9. Таблица executions

CREATE TABLE `executions` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `side` varchar(10) NOT NULL,
  `price` decimal(20,8) NOT NULL,
  `qty` decimal(20,8) NOT NULL,
  `fee` decimal(20,8) DEFAULT NULL,
  `execution_type` varchar(20) NOT NULL,
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE=utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`)),
  PRIMARY KEY (`id`),
  KEY `idx_executions_symbol_time` (`symbol`,`timestamp_ms`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

10. Таблица flows

CREATE TABLE `flows` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `captured_at_utc` datetime NOT NULL,
  `current_price` decimal(20,8) NOT NULL,
  `etp_net_flow_usd` decimal(20,2) DEFAULT NULL,
  `crowd_bias_score` decimal(10,4) DEFAULT NULL,
  `trap_index_score` decimal(10,4) DEFAULT NULL,
  `risk_global_score` decimal(10,4) DEFAULT NULL,
  `warnings_json` longtext DEFAULT NULL,
  `liquidation_json` longtext DEFAULT NULL,
  `etp_summary_json` longtext DEFAULT NULL,
  `payload_json` longtext NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_flows_symbol_time` (`symbol`,`captured_at_utc`),
  KEY `idx_flows_price` (`symbol`,`current_price`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

11. Таблица liquidation_zones

CREATE TABLE `liquidation_zones` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `source` varchar(64) NOT NULL,
  `captured_at_utc` datetime NOT NULL,
  `cluster_id` varchar(64) NOT NULL,
  `side` enum('long','short') NOT NULL,
  `price_level` decimal(20,8) NOT NULL,
  `strength_score` int(11) NOT NULL,
  `size_btc` decimal(20,8) DEFAULT NULL,
  `comment` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_liq_symbol_time` (`symbol`,`captured_at_utc`),
  KEY `idx_liq_symbol_price` (`symbol`,`price_level`),
  KEY `idx_liq_cluster` (`cluster_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

12. Таблица logs

CREATE TABLE `logs` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `module` varchar(32) NOT NULL,
  `level` varchar(16) NOT NULL,
  `message` text NOT NULL,
  `context_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_logs_time` (`created_at_utc`),
  KEY `idx_logs_module` (`module`,`created_at_utc`),
  KEY `idx_logs_level` (`level`,`created_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

13. Таблица market_flow

CREATE TABLE `market_flow` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `price` decimal(20,8) NOT NULL,
  `volume` decimal(20,8) DEFAULT NULL,
  `buy_volume` decimal(20,8) DEFAULT NULL,
  `sell_volume` decimal(20,8) DEFAULT NULL,
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE=utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`)),
  PRIMARY KEY (`id`),
  KEY `idx_market_flow_symbol_time` (`symbol`,`timestamp_ms`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

14. Таблица news_sentiment_history

CREATE TABLE `news_sentiment_history` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `source` varchar(64) NOT NULL,
  `headline` varchar(255) DEFAULT NULL,
  `sentiment_score` decimal(10,4) NOT NULL,
  `sentiment_label` enum('very_bearish','bearish','neutral','bullish','very_bullish') NOT NULL,
  `time_horizon` varchar(32) DEFAULT NULL,
  `payload_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_nsh_symbol_time` (`symbol`,`created_at_utc`),
  KEY `idx_nsh_source` (`source`,`created_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

15. Таблица notifications

CREATE TABLE `notifications` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `channel` varchar(32) NOT NULL,
  `recipient` varchar(128) DEFAULT NULL,
  `level` enum('INFO','WARNING','ERROR','CRITICAL') NOT NULL,
  `category` varchar(64) NOT NULL,
  `title` varchar(255) DEFAULT NULL,
  `message` text NOT NULL,
  `context_json` longtext DEFAULT NULL,
  `status` enum('pending','sent','failed') NOT NULL DEFAULT 'pending',
  `sent_at_utc` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_notifications_time` (`created_at_utc`),
  KEY `idx_notifications_status` (`status`,`created_at_utc`),
  KEY `idx_notifications_channel` (`channel`,`created_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

16. Таблица orders

CREATE TABLE `orders` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `decision_id` bigint(20) UNSIGNED DEFAULT NULL,
  `symbol` varchar(20) NOT NULL,
  `exchange_order_id` varchar(64) DEFAULT NULL,
  `client_order_id` varchar(64) NOT NULL,
  `role` enum('entry','sl','tp1','tp2','liq_exit','manual_exit') NOT NULL,
  `side` enum('buy','sell') NOT NULL,
  `order_type` varchar(32) NOT NULL,
  `status` varchar(32) NOT NULL,
  `reason_code` varchar(64) DEFAULT NULL,
  `price` decimal(20,8) DEFAULT NULL,
  `stop_price` decimal(20,8) DEFAULT NULL,
  `orig_qty` decimal(20,8) NOT NULL,
  `executed_qty` decimal(20,8) NOT NULL DEFAULT 0,
  `avg_fill_price` decimal(20,8) DEFAULT NULL,
  `created_at_utc` datetime NOT NULL,
  `updated_at_utc` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_orders_symbol_time` (`symbol`,`created_at_utc`),
  KEY `idx_orders_client_id` (`client_order_id`),
  KEY `idx_orders_decision` (`decision_id`),
  KEY `idx_orders_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

17. Таблица positions

CREATE TABLE `positions` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `exchange_position_id` varchar(64) DEFAULT NULL,
  `decision_id` bigint(20) UNSIGNED DEFAULT NULL,
  `side` enum('long','short') NOT NULL,
  `status` enum('open','closed') NOT NULL,
  `entry_price` decimal(20,8) NOT NULL,
  `avg_entry_price` decimal(20,8) DEFAULT NULL,
  `size` decimal(20,8) NOT NULL,
  `max_size` decimal(20,8) DEFAULT NULL,
  `sl_price` decimal(20,8) DEFAULT NULL,
  `tp1_price` decimal(20,8) DEFAULT NULL,
  `tp2_price` decimal(20,8) DEFAULT NULL,
  `opened_at_utc` datetime NOT NULL,
  `closed_at_utc` datetime DEFAULT NULL,
  `pnl_usdt` decimal(20,8) DEFAULT NULL,
  `pnl_pct` decimal(10,4) DEFAULT NULL,
  `tp1_hit` tinyint(1) NOT NULL DEFAULT 0,
  `tp2_hit` tinyint(1) NOT NULL DEFAULT 0,
  `liq_exit_used` tinyint(1) NOT NULL DEFAULT 0,
  `risk_mode_at_open` enum('risk_off','cautious','neutral','aggressive') DEFAULT NULL,
  `position_management_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_positions_symbol_status` (`symbol`,`status`),
  KEY `idx_positions_open_time` (`opened_at_utc`),
  KEY `idx_positions_decision` (`decision_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

18. Таблица reconciliation_events

CREATE TABLE `reconciliation_events` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `module` varchar(32) NOT NULL,
  `run_id` varchar(64) DEFAULT NULL,
  `result` enum('ok','warning','error') NOT NULL,
  `summary` varchar(255) DEFAULT NULL,
  `details_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_recon_time` (`created_at_utc`),
  KEY `idx_recon_module` (`module`,`created_at_utc`),
  KEY `idx_recon_result` (`result`,`created_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

19. Таблица risk_events

CREATE TABLE `risk_events` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `symbol` varchar(20) DEFAULT NULL,
  `event_type` varchar(64) NOT NULL,
  `old_value` varchar(64) DEFAULT NULL,
  `new_value` varchar(64) DEFAULT NULL,
  `details` text DEFAULT NULL,
  `details_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_risk_events_time` (`created_at_utc`),
  KEY `idx_risk_events_type` (`event_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

20. Таблица snapshots

CREATE TABLE `snapshots` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `captured_at_utc` datetime NOT NULL,
  `price` decimal(20,8) NOT NULL,
  `timeframe` varchar(16) NOT NULL,
  `structure_tag` varchar(32) DEFAULT NULL,
  `momentum_tag` varchar(32) DEFAULT NULL,
  `atr_5m` decimal(20,8) DEFAULT NULL,
  `session` varchar(16) DEFAULT NULL,
  `payload_json` longtext NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_snapshots_symbol_time` (`symbol`,`captured_at_utc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

21. Таблица trades

CREATE TABLE `trades` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `decision_id` bigint(20) UNSIGNED DEFAULT NULL,
  `symbol` varchar(20) NOT NULL,
  `side` enum('long','short') NOT NULL,
  `entry_price` decimal(20,8) NOT NULL,
  `avg_entry_price` decimal(20,8) DEFAULT NULL,
  `exit_price` decimal(20,8) NOT NULL,
  `avg_exit_price` decimal(20,8) DEFAULT NULL,
  `quantity` decimal(20,8) NOT NULL,
  `pnl_usdt` decimal(20,8) NOT NULL,
  `pnl_pct` decimal(10,4) NOT NULL,
  `max_adverse_excursion` decimal(10,4) DEFAULT NULL,
  `max_favorable_excursion` decimal(10,4) DEFAULT NULL,
  `opened_at_utc` datetime NOT NULL,
  `closed_at_utc` datetime NOT NULL,
  `exit_reason` enum('tp1','tp2','sl','liq_exit','risk_off','manual','other') NOT NULL,
  `tp1_hit` tinyint(1) NOT NULL DEFAULT 0,
  `tp2_hit` tinyint(1) NOT NULL DEFAULT 0,
  `position_management_json` longtext DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_trades_symbol_time` (`symbol`,`opened_at_utc`),
  KEY `idx_trades_closed_time` (`symbol`,`closed_at_utc`),
  KEY `idx_trades_decision` (`decision_id`),
  KEY `idx_trades_exit_reason` (`exit_reason`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

::contentReference[oaicite:0]{index=0}