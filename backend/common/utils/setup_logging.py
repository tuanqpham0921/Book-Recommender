"""Bootstrap logging for the application."""

import logging
import os
import sys
from pathlib import Path

from rich.logging import RichHandler

"""
DEBUG, INFO, WARNING, ERROR, CRITICAL
"""
PLAIN_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s:%(funcName)s:%(lineno)d - %(message)s"
)

FILE_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
)

RICH_LOG_FORMAT = "| %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_FILE = "logs/dev_log.log"


def setup_logging(
    environment: str,
    log_file: Path | str = LOG_FILE,
    overwrite: bool = True,
) -> None:
    """Setup logging for the application."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    handlers: list[logging.Handler] = []
    use_plain_logs = os.getenv("CI") or os.getenv("PYTEST_CURRENT_TEST")
    if use_plain_logs:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter(PLAIN_LOG_FORMAT, datefmt=DATE_FORMAT)
        )
    else:
        console_handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_level=True,
            show_path=False,
        )
        console_handler.setFormatter(
            logging.Formatter(RICH_LOG_FORMAT, datefmt=DATE_FORMAT)
        )
    handlers.append(console_handler)

    if environment.lower() == "development":
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = "w" if overwrite else "a"
        file_handler = logging.FileHandler(log_path, mode=file_mode, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(FILE_LOG_FORMAT, datefmt=DATE_FORMAT)
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        handlers=handlers,
        force=True,
    )

    logger = logging.getLogger(__name__)
    logger.info("Logging setup for environment: %s", environment)
    logger.info("Log level: %s", log_level)
    logger.info("Handlers: %s", [type(handler).__name__ for handler in handlers])

    if environment.lower() == "development":
        logger.info("Log file: %s", log_file)
    else:
        logger.info("Not saving log to file in production environment")
