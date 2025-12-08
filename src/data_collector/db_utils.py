"""Utility helpers for legacy data collectors.

Uses the centralized database settings so that pymysql connections are created
the same way across the project.
"""

import sys

import pymysql

from src.db.settings import load_database_settings


def get_db_connection():
    """
    Возвращает pymysql connection к MariaDB.

    Используем параметры из блока "database" конфига или переменные среды
    (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME).
    """
    db_settings = load_database_settings()

    conn = pymysql.connect(
        host=db_settings.host,
        port=db_settings.port,
        user=db_settings.user,
        password=db_settings.password,
        database=db_settings.name,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
    )

    return conn


if __name__ == "__main__":
    # Простой тест подключения
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
        conn.close()
        print("DB connection OK, SELECT 1 ->", row)
    except Exception as e:
        print("DB connection FAILED:", e, file=sys.stderr)
        sys.exit(1)
