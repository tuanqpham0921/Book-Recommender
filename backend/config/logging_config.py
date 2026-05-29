import logging
import os
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_FILE = "logs/dev_log.log"

def setup_logging(environment: str) -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", LOG_FILE)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if environment.lower() == "development":
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers,
        force=True,
    )

    logger = logging.getLogger(__name__)
    logger.info("Logging setup for environment: %s", environment)
    logger.info("Log level: %s", log_level)
    logger.info("Handlers: %s", [type(handler).__name__ for handler in handlers])