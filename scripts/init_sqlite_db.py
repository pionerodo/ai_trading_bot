import sqlite3
from pathlib import Path

DB_PATH = Path("db/ai_trading_bot_dev.sqlite")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS candles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT NOT NULL,
    timeframe    TEXT NOT NULL,
    open_time    TEXT NOT NULL,   -- ISO UTC
    close_time   TEXT NOT NULL,
    open_price   REAL NOT NULL,
    high_price   REAL NOT NULL,
    low_price    REAL NOT NULL,
    close_price  REAL NOT NULL,
    volume       REAL NOT NULL,
    quote_volume REAL,
    trades_count INTEGER,
    UNIQUE(symbol, timeframe, open_time)
);

CREATE TABLE IF NOT EXISTS derivatives (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    open_interest   REAL,
    funding_rate    REAL,
    funding_interval TEXT,
    taker_buy_volume  REAL,
    taker_sell_volume REAL,
    taker_buy_ratio   REAL,
    basis            REAL,
    basis_pct        REAL,
    cvd_1h           REAL,
    cvd_4h           REAL,
    extra_json       TEXT
);

/* по желанию: snapshots, flows, decisions и т.д. — по сокращённой схеме */
"""

def main():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        print(f"SQLite dev DB init: {DB_PATH}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
