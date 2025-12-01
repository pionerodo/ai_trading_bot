import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any

from .config_loader import get_base_dir


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    base_dir: Path = get_base_dir()
    logging_cfg = config.get("logging", {})

    log_level_str = str(logging_cfg.get("level", "INFO")).upper()
    level = getattr(logging, log_level_str, logging.INFO)

    log_file_rel = logging_cfg.get("file", "logs/bot.log")
    log_file = base_dir / log_file_rel
    log_file.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = int(logging_cfg.get("max_bytes", 10 * 1024 * 1024))
    backup_count = int(logging_cfg.get("backup_count", 5))

    logger = logging.getLogger("ai_trading_bot")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)

    return logger

