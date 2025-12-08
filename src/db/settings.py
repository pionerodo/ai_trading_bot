"""Centralized database settings sourced from environment and config.

This module keeps the database configuration in one place so that scripts and
services do not duplicate connection logic. Environment variables take
precedence over YAML configuration, but configuration values remain as a
fallback for local development. Required settings are validated at runtime.
"""

from dataclasses import dataclass
from typing import Dict, Optional

import os

from src.core.config_loader import load_config


# Environment variable names used across the project
DB_ENV_VARS = {
    "host": "DB_HOST",
    "port": "DB_PORT",
    "user": "DB_USER",
    "password": "DB_PASSWORD",
    "name": "DB_NAME",
}


@dataclass
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    name: str
    echo: bool = False

    @property
    def url(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/"
            f"{self.name}?charset=utf8mb4"
        )


def _load_database_block() -> Dict[str, str]:
    """Read the ``database`` block from config.yaml (if present)."""

    cfg = load_config()
    db_cfg = cfg.get("database") or {}
    return db_cfg


def _get_setting(name: str, db_cfg: Dict[str, str]) -> Optional[str]:
    env_value = os.getenv(DB_ENV_VARS[name])
    if env_value is not None:
        return env_value

    cfg_value = db_cfg.get(name)
    if cfg_value is not None:
        return str(cfg_value)

    return None


def load_database_settings() -> DatabaseSettings:
    """Load DB settings from environment (preferred) or config, with validation."""

    db_cfg = _load_database_block()

    settings: Dict[str, Optional[str]] = {
        key: _get_setting(key, db_cfg) for key in DB_ENV_VARS
    }

    missing = [key for key, value in settings.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing database settings: "
            + ", ".join(missing)
            + ". Set environment variables "
            + ", ".join(DB_ENV_VARS.values())
            + " or provide them under the 'database' section in config.yaml."
        )

    return DatabaseSettings(
        host=settings["host"],
        port=int(settings["port"]),
        user=settings["user"],
        password=settings["password"],
        name=settings["name"],
        echo=bool(db_cfg.get("echo", False)),
    )


def validate_required_env_vars() -> None:
    """Fail fast when required database environment variables are missing."""

    missing_env = [name for name in DB_ENV_VARS.values() if os.getenv(name) is None]
    if missing_env:
        raise RuntimeError(
            "Required environment variables are not set: " + ", ".join(missing_env)
        )
