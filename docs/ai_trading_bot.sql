-- phpMyAdmin SQL Dump
-- version 5.2.2
-- https://www.phpmyadmin.net/
--
-- Хост: localhost
-- Время создания: Дек 08 2025 г., 00:15
-- Версия сервера: 10.11.10-MariaDB-log
-- Версия PHP: 8.3.25

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- База данных: `ai_trading_bot`
--

-- --------------------------------------------------------

--
-- Структура таблицы `bot_state`
--

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

-- --------------------------------------------------------

--
-- Структура таблицы `candles`
--

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
  `close_time` bigint(20) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `decisions`
--

CREATE TABLE `decisions` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `created_at_utc` datetime DEFAULT NULL,
  `symbol` varchar(20) NOT NULL,
  `timestamp` datetime DEFAULT NULL,
  `timeframe` varchar(16) NOT NULL DEFAULT '5m',
  `action` enum('long','short','flat') NOT NULL,
  `confidence` float NOT NULL,
  `risk_checks_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`risk_checks_json`)),
  `snapshot_id` bigint(20) DEFAULT NULL,
  `flow_id` bigint(20) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `reason` text DEFAULT NULL,
  `entry_min_price` decimal(20,8) DEFAULT NULL,
  `entry_max_price` decimal(20,8) DEFAULT NULL,
  `sl_price` decimal(20,8) DEFAULT NULL,
  `tp1_price` decimal(20,8) DEFAULT NULL,
  `tp2_price` decimal(20,8) DEFAULT NULL,
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
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `derivatives`
--

CREATE TABLE `derivatives` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `open_interest` double DEFAULT NULL,
  `funding_rate` double DEFAULT NULL,
  `taker_buy_volume` double DEFAULT NULL,
  `taker_sell_volume` double DEFAULT NULL,
  `taker_buy_ratio` double DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `equity_curve`
--

CREATE TABLE `equity_curve` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `captured_at_utc` datetime NOT NULL,
  `equity_usdt` decimal(20,8) NOT NULL,
  `balance_usdt` decimal(20,8) NOT NULL,
  `open_pnl_usdt` decimal(20,8) NOT NULL,
  `closed_pnl_usdt` decimal(20,8) NOT NULL,
  `daily_dd_pct` decimal(10,4) NOT NULL,
  `weekly_dd_pct` decimal(10,4) NOT NULL,
  `risk_mode` enum('risk_off','cautious','neutral','aggressive') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `etp_flows`
--

CREATE TABLE `etp_flows` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `date_utc` date NOT NULL,
  `source` varchar(64) NOT NULL,
  `payload_json` longtext NOT NULL,
  `total_net_flow_usd` decimal(20,2) DEFAULT NULL,
  `notes` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `executions`
--

CREATE TABLE `executions` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `side` varchar(10) NOT NULL,
  `price` decimal(20,8) NOT NULL,
  `qty` decimal(20,8) NOT NULL,
  `status` varchar(20) NOT NULL,
  `exchange_order_id` varchar(64) DEFAULT NULL,
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `flows`
--

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
  `payload_json` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `liquidation_zones`
--

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
  `comment` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `logs`
--

CREATE TABLE `logs` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `timestamp` datetime NOT NULL DEFAULT current_timestamp(),
  `created_at_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `module` varchar(255) DEFAULT NULL,
  `level` varchar(16) NOT NULL,
  `source` varchar(64) NOT NULL DEFAULT 'unknown',
  `message` text NOT NULL,
  `context` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`context`)),
  `context_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `market_flow`
--

CREATE TABLE `market_flow` (
  `id` bigint(20) NOT NULL,
  `timestamp_ms` bigint(20) NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `crowd_sentiment` float DEFAULT NULL,
  `funding_rate` float DEFAULT NULL,
  `open_interest_change` float DEFAULT NULL,
  `liquidations_long` float DEFAULT NULL,
  `liquidations_short` float DEFAULT NULL,
  `risk_score` float DEFAULT NULL,
  `json_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`json_data`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `news_sentiment_history`
--

CREATE TABLE `news_sentiment_history` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `symbol` varchar(20) NOT NULL,
  `source` varchar(64) NOT NULL,
  `headline` varchar(255) DEFAULT NULL,
  `sentiment_score` decimal(10,4) NOT NULL,
  `sentiment_label` enum('very_bearish','bearish','neutral','bullish','very_bullish') NOT NULL,
  `time_horizon` varchar(32) DEFAULT NULL,
  `payload_json` longtext DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `notifications`
--

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
  `sent_at_utc` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `orders`
--

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
  `executed_qty` decimal(20,8) NOT NULL DEFAULT 0.00000000,
  `avg_fill_price` decimal(20,8) DEFAULT NULL,
  `created_at_utc` datetime NOT NULL,
  `updated_at_utc` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `positions`
--

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
  `position_management_json` longtext DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `reconciliation_events`
--

CREATE TABLE `reconciliation_events` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL,
  `module` varchar(32) NOT NULL,
  `run_id` varchar(64) DEFAULT NULL,
  `result` enum('ok','warning','error') NOT NULL,
  `summary` varchar(255) DEFAULT NULL,
  `details_json` longtext DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `risk_events`
--

CREATE TABLE `risk_events` (
  `id` bigint(20) UNSIGNED NOT NULL,
  `created_at_utc` datetime NOT NULL DEFAULT current_timestamp(),
  `symbol` varchar(20) DEFAULT NULL,
  `event_type` varchar(64) NOT NULL,
  `old_value` varchar(64) DEFAULT NULL,
  `new_value` varchar(64) DEFAULT NULL,
  `details` text DEFAULT NULL,
  `details_json` longtext DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `timestamp` datetime NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `snapshots`
--

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
  `payload_json` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Структура таблицы `trades`
--

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
  `position_management_json` longtext DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Индексы сохранённых таблиц
--

--
-- Индексы таблицы `bot_state`
--
ALTER TABLE `bot_state`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `candles`
--
ALTER TABLE `candles`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `symbol` (`symbol`,`timeframe`,`open_time`);

--
-- Индексы таблицы `decisions`
--
ALTER TABLE `decisions`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `symbol` (`symbol`,`timestamp_ms`),
  ADD KEY `idx_decisions_symbol_time` (`symbol`,`created_at_utc`),
  ADD KEY `idx_decisions_action` (`symbol`,`action`,`created_at_utc`),
  ADD KEY `idx_decisions_risk_mode` (`risk_mode`,`created_at_utc`),
  ADD KEY `idx_decisions_snapshot` (`snapshot_ref_id`),
  ADD KEY `idx_decisions_flow` (`flow_ref_id`);

--
-- Индексы таблицы `derivatives`
--
ALTER TABLE `derivatives`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `symbol_ts` (`symbol`,`timestamp_ms`);

--
-- Индексы таблицы `equity_curve`
--
ALTER TABLE `equity_curve`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_equity_time` (`captured_at_utc`),
  ADD KEY `idx_equity_mode` (`risk_mode`,`captured_at_utc`);

--
-- Индексы таблицы `etp_flows`
--
ALTER TABLE `etp_flows`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_etp_symbol_date_source` (`symbol`,`date_utc`,`source`),
  ADD KEY `idx_etp_date` (`date_utc`);

--
-- Индексы таблицы `executions`
--
ALTER TABLE `executions`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `flows`
--
ALTER TABLE `flows`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_flows_symbol_time` (`symbol`,`captured_at_utc`),
  ADD KEY `idx_flows_price` (`symbol`,`current_price`);

--
-- Индексы таблицы `liquidation_zones`
--
ALTER TABLE `liquidation_zones`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_liq_symbol_time` (`symbol`,`captured_at_utc`),
  ADD KEY `idx_liq_symbol_price` (`symbol`,`price_level`),
  ADD KEY `idx_liq_cluster` (`cluster_id`);

--
-- Индексы таблицы `logs`
--
ALTER TABLE `logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_logs_time` (`created_at_utc`),
  ADD KEY `idx_logs_module` (`module`,`created_at_utc`),
  ADD KEY `idx_logs_level` (`level`,`created_at_utc`);

--
-- Индексы таблицы `market_flow`
--
ALTER TABLE `market_flow`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `symbol` (`symbol`,`timestamp_ms`);

--
-- Индексы таблицы `news_sentiment_history`
--
ALTER TABLE `news_sentiment_history`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_nsh_symbol_time` (`symbol`,`created_at_utc`),
  ADD KEY `idx_nsh_source` (`source`,`created_at_utc`);

--
-- Индексы таблицы `notifications`
--
ALTER TABLE `notifications`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_notifications_time` (`created_at_utc`),
  ADD KEY `idx_notifications_status` (`status`,`created_at_utc`),
  ADD KEY `idx_notifications_channel` (`channel`,`created_at_utc`);

--
-- Индексы таблицы `orders`
--
ALTER TABLE `orders`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_orders_symbol_time` (`symbol`,`created_at_utc`),
  ADD KEY `idx_orders_client_id` (`client_order_id`),
  ADD KEY `idx_orders_decision` (`decision_id`),
  ADD KEY `idx_orders_role` (`role`);

--
-- Индексы таблицы `positions`
--
ALTER TABLE `positions`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_positions_symbol_status` (`symbol`,`status`),
  ADD KEY `idx_positions_open_time` (`opened_at_utc`),
  ADD KEY `idx_positions_decision` (`decision_id`);

--
-- Индексы таблицы `reconciliation_events`
--
ALTER TABLE `reconciliation_events`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_recon_time` (`created_at_utc`),
  ADD KEY `idx_recon_module` (`module`,`created_at_utc`),
  ADD KEY `idx_recon_result` (`result`,`created_at_utc`);

--
-- Индексы таблицы `risk_events`
--
ALTER TABLE `risk_events`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_risk_events_time` (`created_at_utc`),
  ADD KEY `idx_risk_events_type` (`event_type`);

--
-- Индексы таблицы `snapshots`
--
ALTER TABLE `snapshots`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_snapshots_symbol_time` (`symbol`,`captured_at_utc`);

--
-- Индексы таблицы `trades`
--
ALTER TABLE `trades`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_trades_symbol_time` (`symbol`,`opened_at_utc`),
  ADD KEY `idx_trades_closed_time` (`symbol`,`closed_at_utc`),
  ADD KEY `idx_trades_decision` (`decision_id`),
  ADD KEY `idx_trades_exit_reason` (`exit_reason`);

--
-- AUTO_INCREMENT для сохранённых таблиц
--

--
-- AUTO_INCREMENT для таблицы `candles`
--
ALTER TABLE `candles`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `decisions`
--
ALTER TABLE `decisions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `derivatives`
--
ALTER TABLE `derivatives`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `equity_curve`
--
ALTER TABLE `equity_curve`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `etp_flows`
--
ALTER TABLE `etp_flows`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `executions`
--
ALTER TABLE `executions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `flows`
--
ALTER TABLE `flows`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `liquidation_zones`
--
ALTER TABLE `liquidation_zones`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `logs`
--
ALTER TABLE `logs`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `market_flow`
--
ALTER TABLE `market_flow`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `news_sentiment_history`
--
ALTER TABLE `news_sentiment_history`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `notifications`
--
ALTER TABLE `notifications`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `orders`
--
ALTER TABLE `orders`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `positions`
--
ALTER TABLE `positions`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `reconciliation_events`
--
ALTER TABLE `reconciliation_events`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `risk_events`
--
ALTER TABLE `risk_events`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `snapshots`
--
ALTER TABLE `snapshots`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `trades`
--
ALTER TABLE `trades`
  MODIFY `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
