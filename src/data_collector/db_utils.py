"""
db_utils.py

Единая точка подключения к MariaDB для всего проекта.

Логика:
- читаем config/config.local.yaml (если есть),
- иначе читаем config/config.yaml,
- берём блок "database",
- создаём подключение через pymysql.
"""

import os
import sys
from typing import Any, Dict

import pymysql
import yaml


def _load_config() -> Dict[str, Any]:
    """
    Загружаем конфиг из config.local.yaml (если есть) или config.yaml.
    Ожидаем структуру:

    database:
      host: "127.0.0.1"
      port: 3306
      user: "ai_trading_bot"
      password: "********"
      name: "ai_trading_bot"
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # base_dir = /.../ai_trading_bot

    config_dir = os.path.join(base_dir, "config")

    local_path = os.path.join(config_dir, "config.local.yaml")
    main_path = os.path.join(config_dir, "config.yaml")

    path = None
    if os.path.exists(local_path):
        path = local_path
    elif os.path.exists(main_path):
        path = main_path

    if path is None:
        raise RuntimeError("db_utils: no config.yaml or config.local.yaml found in ./config")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    return cfg


def get_db_connection():
    """
    Возвращает pymysql connection к MariaDB.

    Используем параметры из блока "database" конфига.
    """
    cfg = _load_config()
    db_cfg = cfg.get("database") or {}

    host = db_cfg.get("host", "127.0.0.1")
    port = int(db_cfg.get("port", 3306))
    user = db_cfg.get("user")
    password = db_cfg.get("password")
    name = db_cfg.get("name")

    if not all([user, password, name]):
        raise RuntimeError(
            "db_utils: database.user / database.password / database.name "
            "must be set in config.yaml or config.local.yaml"
        )

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=name,
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
