"""Logging configuration for JARVIS."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def default_log_dir() -> Path:
    """Return the directory used for log files."""
    base = os.environ.get("JARVIS_HOME")
    if base:
        root = Path(base).expanduser()
    else:
        root = Path.home() / ".jarvis"
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(level: str = "INFO", *, quiet_console: bool = False) -> logging.Logger:
    """Configure root logging and return the ``jarvis`` logger."""
    numeric = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if not quiet_console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(numeric)
        root.addHandler(stream)

    try:
        file_handler = logging.FileHandler(default_log_dir() / "jarvis.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(min(numeric, logging.DEBUG))
        root.addHandler(file_handler)
    except OSError:  # pragma: no cover - read-only home
        pass

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logger = logging.getLogger("jarvis")
    logger.setLevel(numeric)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"jarvis.{name}")
