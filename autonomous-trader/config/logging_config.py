"""
config/logging_config.py
========================
Configures structured logging for the entire system.
Every module imports `get_logger(__name__)` from here.

Log format: 2025-01-01 09:15:00 | INFO     | agents.decision | [RELIANCE.NS] Decision: BUY

Logs are written to:
  1. Console (stdout) — always active
  2. Rotating log file — max 50MB, keeps last 10 files

Usage:
    from config.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("[RELIANCE.NS] Technical score: 7.4")
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    """
    Initialises the root logger. Call this ONCE at application startup
    (e.g., in api/main.py or orchestrator/scheduler.py).

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR
        log_file: Absolute or relative path to the log file.
                  If None, logs to console only.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(fmt)
    root_logger.addHandler(console_handler)

    # Rotating file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=50 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ["urllib3", "httpx", "httpcore", "asyncio", "yfinance", "peewee"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for very_noisy in ["tensorflow", "absl"]:
        logging.getLogger(very_noisy).setLevel(logging.ERROR)

    root_logger.info(
        f"Logging initialised | level={log_level} | "
        f"file={'disabled' if not log_file else log_file}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger for a module.

    Typical usage at the top of each file:
        from config.logging_config import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)


def setup_logging_from_settings() -> None:
    """
    Reads LOG_LEVEL and LOG_FILE from settings and calls setup_logging().
    Use this at application entry points.
    """
    try:
        from config.settings import settings
        setup_logging(
            log_level=settings.LOG_LEVEL,
            log_file=str(settings.log_file_resolved),
        )
    except Exception as e:
        setup_logging(log_level="INFO")
        logging.getLogger(__name__).warning(
            f"Could not load settings for logging setup: {e}. Using defaults."
        )
