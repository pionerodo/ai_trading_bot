import sqlite3
import pymysql
from datetime import datetime, timedelta
from pathlib import Path

import sys
from pathlib import Path as P

# Поднимаем project root для корректного импорта src.*
PROJECT_ROOT = str(P(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.db.settings import load_database_settings


SQLITE_PATH = Path("db/ai_trading_bot_dev.sqlite")


def main():
    db_settings = load_database_settings()

    # Подключение к MariaDB через конфиг
    conn_mysql = pymysql.connect(
        host=db_settings.host,
        port=db_settings.port,
        user=db_settings.user,
        password=db_settings.password,
        database=db_settings.name,   # <-- ВАЖНО: name из config.yaml/env
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    # Подключение к SQLite
    SQLITE_PATH.parent.mkdir(exist_ok=True)
    conn_sqlite = sqlite3.connect(SQLITE_PATH)

    try:
        # Берём последние 2 дня 1m-свечей BTCUSDT
        since = datetime.utcnow() - timedelta(days=2)

        with conn_mysql.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, timeframe, open_time, close_time,
                       open_price, high_price, low_price, close_price,
                       volume, quote_volume, trades_count
                FROM candles
                WHERE symbol = %s
                  AND timeframe = %s
                  AND open_time >= %s
                ORDER BY open_time
                """,
                ("BTCUSDT", "1m", since),
            )
            rows = cur.fetchall()

        cur_sql = conn_sqlite.cursor()

        # Чистим dev-таблицу (это только песочница для Codex)
        cur_sql.execute("DELETE FROM candles")

        for r in rows:
            cur_sql.execute(
                """
                INSERT INTO candles (
                    symbol, timeframe,
                    open_time, close_time,
                    open_price, high_price, low_price, close_price,
                    volume, quote_volume, trades_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["symbol"],
                    r["timeframe"],
                    r["open_time"].strftime("%Y-%m-%dT%H:%M:%S"),
                    r["close_time"].strftime("%Y-%m-%dT%H:%M:%S"),
                    float(r["open_price"]),
                    float(r["high_price"]),
                    float(r["low_price"]),
                    float(r["close_price"]),
                    float(r["volume"]),
                    float(r["quote_volume"]) if r["quote_volume"] is not None else None,
                    r["trades_count"],
                ),
            )

        conn_sqlite.commit()
        print(f"✓ Synced {len(rows)} candles → {SQLITE_PATH}")

    finally:
        conn_mysql.close()
        conn_sqlite.close()


if __name__ == "__main__":
    main()
