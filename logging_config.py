# logging_config.py
import logging
from logging.handlers import RotatingFileHandler
import os

LOG_DIR = "."
LOG_FILE = os.path.join(LOG_DIR, "bgp_manager.log")

# Create logger
logger = logging.getLogger("bgp_manager")
logger.setLevel(logging.DEBUG)

# Avoid duplicate handlers if reloaded
if not logger.handlers:
    # File handler (rotating)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s | %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler (for dev)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)


# Helper to get logger in other modules
def get_logger(name: str = None):
    return logging.getLogger(name or "bgp_manager")
