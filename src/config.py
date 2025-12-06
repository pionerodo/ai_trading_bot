"""Lightweight configuration helpers for execution-time settings.

Values are primarily sourced from environment variables to keep secrets
out of the repository. For Binance access, API keys must be provided via
environment variables; no defaults are embedded in code.
"""

import os
from dataclasses import dataclass


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class BinanceConfig:
    api_key: str
    api_secret: str
    testnet: bool = True
    base_asset: str = "BTCUSDT"


def get_binance_config() -> BinanceConfig:
    """Load Binance credentials/settings from environment.

    Expected variables:
    - BINANCE_API_KEY
    - BINANCE_API_SECRET
    - BINANCE_TESTNET (optional, defaults to True)
    - BINANCE_BASE_ASSET (optional, defaults to BTCUSDT)
    """

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are required for Binance access")

    testnet = _get_env_bool("BINANCE_TESTNET", True)
    base_asset = os.getenv("BINANCE_BASE_ASSET", "BTCUSDT")

    return BinanceConfig(api_key=api_key, api_secret=api_secret, testnet=testnet, base_asset=base_asset)
