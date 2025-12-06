import logging
import sys

from src.db.session import SessionLocal
from src.execution.execution_loop import run_single_cycle


logger = logging.getLogger(__name__)


def main(symbol: str = "BTCUSDT") -> None:
    """Thin cron-safe entrypoint that runs a single execution cycle and exits."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        run_single_cycle(db_session_factory=SessionLocal, symbol=symbol)
    except Exception:
        logger.exception("Execution cycle failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
