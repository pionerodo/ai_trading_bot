AI Trading Bot — PROJECT OVERVIEW

1. Purpose of the Project

AI Trading Bot is a fully autonomous BTCUSDT trading system built around:

deterministic analytics,

rule‑based decision making,

strict risk management,

robust execution,

full auditability via logs and database.

The system operates continuously on server infrastructure and executes trades through exchange APIs.

2. Core Architecture

The project follows a modular architecture (defined in the Technical Specification):

2.1 Data Pipeline

Located in /src/data_pipeline/.

Collects market snapshots.

Processes flows: derivatives, ETF, liquidation maps.

Normalizes all inputs to strict JSON schemas.

Writes results into MariaDB + JSON files.

2.2 Analytics Engine

Located in /src/analytics_engine/.

decision_engine.py — determines LONG / SHORT / FLAT.

risk_manager.py — applies all risk constraints and overrides.

Generates decision.json every 5 minutes.

2.3 Execution Engine

Located in /src/execution_engine/.

Reads decision.json.

Opens/closes positions.

Manages SL/TP.

Handles liquidation‑based exits and trailing logic.

Reconciles orders on restart.

2.4 Database

Defined in DATABASE_SCHEMA.md.

candles

snapshots

flows

decisions

orders

trades

equity_curve

logs

notifications

2.5 Backtesting Engine

Located in /src/backtest_engine/.

Supports 1‑day and 3‑day quick tests.

Uses real data from the pipeline.

3. Technical Specification (TЗ)

The official documentation for the entire project includes:

README.md

ARCHITECTURE.md

DATA_PIPELINE.md

DECISION_ENGINE.md

EXECUTION_ENGINE.md

RISK_MANAGER.md

BACKTESTING.md

DATABASE_SCHEMA.md

INPUT_FORMATS.md

DASHBOARD.md

MILESTONES.md

This documentation is the single source of truth. All development must strictly follow it.

4. Position Management Rules (v1.1)

These rules are mandatory across the system.

4.1 Stop Loss

Minimum SL = 0.35% of entry price.

SL never expands.

After TP1, SL is moved to breakeven or better.

4.2 Risk‑Reward

Minimum RR ≥ 2.0 for TP1.

If RR < 2 — trade is invalid.

4.3 Take Profit Logic

TP1 = partial exit (usually 50%).

TP2 = structure + liquidation cluster.

TP may be dynamically updated if new clusters appear.

4.4 Liquidation‑Based Exit

If price enters selected liq‑zone → partial closure or full exit.

Trailing SL becomes more aggressive.

4.5 Trailing Mode

structure_plus_liq:

Trail based on swing structure.

Trail accelerates near liquidation clusters.

5. Deployment Workflow

Server: Hetzner CPX21 Location: /www/wwwroot/ai-hedge.cryptobavaro.online/

Deployment Steps

Make changes in Codex.

Commit + push to GitHub.

On server:

git pull

Restart necessary services (systemd or cron jobs).

The server never updates automatically — deployment is always manual to avoid accidents.

6. How Codex Works with This Project

Codex pulls the GitHub repository and works inside an isolated environment.

When changes are accepted, they are committed to the repo.

The server must pull updates manually.

All tasks given to Codex must reference this documentation.

Recommended instruction for Codex in tasks:

Работаем строго в проекте AI Trading Bot.
Источник истины — файлы ТЗ (.md).
Любая логика должна соответствовать DECISION_ENGINE.md, EXECUTION_ENGINE.md, RISK_MANAGER.md.
Не придумывать ничего сверх ТЗ.

7. Recommended Folder Structure

/src
  /analytics_engine
    decision_engine.py
    risk_manager.py
  /execution_engine
    execution_loop.py
  /data_pipeline
    collectors...
  /backtest_engine

/config.py
/requirements.txt
/TZ documents (.md)

8. Current Development Priorities

Update DECISION_ENGINE.md and EXECUTION_ENGINE.md with final v1.1 logic.

Implement full Position Management in code.

Add structured logs for execution.

Improve backtesting accuracy.

Expand analytics dashboard.

9. Notes

This file serves as the high‑level passport of the AI Trading Bot project. Use it for orientation when working across Codex, GitHub, and the server.

