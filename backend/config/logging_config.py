import json
import logging
import os
from typing import Optional

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_FILE = "logs/dev_log.log"

def setup_logging(environment: str):
    
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    handlers = [logging.StreamHandler()]
    if environment == "development":
        handlers.append(logging.FileHandler(LOG_FILE))
    
    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers,
        force=True,
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging setup for environment: {environment}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Log level: {log_level}")
    logger.info(f"Handlers: {handlers}")