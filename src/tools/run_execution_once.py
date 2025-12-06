"""Manual single-cycle runner for the execution engine.

This is a thin wrapper around execution_loop.run_single_cycle intended for
manual smoke-tests. It exits after one cycle and is safe to run under cron.
"""

import logging
import sys
from typing import Optional

from src.db.session import SessionLocal
from src.execution.execution_loop import run_single_cycle


logger = logging.getLogger(__name__)


def notify_critical(message: str, context: Optional[dict] = None) -> None:
    logger.warning("NOTIFY: %s | %s", message, context or {})


def main(symbol: str = "BTCUSDT") -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        run_single_cycle(db_session_factory=SessionLocal, symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Execution cycle failed")
        notify_critical("Execution cycle failed", {"error": str(exc), "symbol": symbol})
        sys.exit(1)


if __name__ == "__main__":
    main()
