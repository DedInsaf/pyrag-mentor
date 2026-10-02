"""Console and rotating-file logging configuration."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from backend.core.config import Settings, get_settings


def build_logging_config(settings: Settings) -> dict[str, Any]:
    """Build a dictConfig payload without mutating global logging state."""

    log_path = settings.log_file_path
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": (
                    "%(asctime)s | %(levelname)s | %(name)s | "
                    "%(filename)s:%(lineno)d | %(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "format": (
                    "%(asctime)s | %(levelname)s | %(client_addr)s | "
                    "%(request_line)s | %(status_code)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": settings.log_level,
                "stream": "ext://sys.stdout",
            },
            "rotating_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "level": settings.log_level,
                "filename": str(log_path),
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "rotating_file"],
            "level": settings.log_level,
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console", "rotating_file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "rotating_file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "rotating_file"],
                "level": "INFO",
                "propagate": False,
            },
            "httpx": {
                "handlers": ["console", "rotating_file"],
                "level": "WARNING",
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "handlers": ["console", "rotating_file"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }


def setup_logging(settings: Settings | None = None) -> Path:
    """Create the log directory and configure console/file handlers."""

    resolved_settings = settings or get_settings()
    resolved_settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(build_logging_config(resolved_settings))
    return resolved_settings.log_file_path
