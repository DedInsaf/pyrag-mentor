"""Tests for console and rotating-file logging."""

import logging
from pathlib import Path

from backend.core.config import Settings
from backend.utils.logging import setup_logging


def test_setup_logging_writes_to_file(tmp_path: Path) -> None:
    settings = Settings(
        log_dir=tmp_path,
        log_file_name="test.log",
        log_level="INFO",
    )

    log_path = setup_logging(settings)
    logging.getLogger("tests.logging").info("stage-two-log-message")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_path.exists()
    assert "stage-two-log-message" in log_path.read_text(encoding="utf-8")
