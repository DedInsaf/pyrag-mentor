"""Tests for typed environment configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.constants import LLMProvider


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_NAME", "Test Mentor")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("CORS_ORIGINS", "http://one.test, http://two.test")

    settings = Settings()

    assert settings.project_name == "Test Mentor"
    assert settings.api_port == 9000
    assert settings.llm_provider is LLMProvider.HUGGING_FACE
    assert settings.cors_origin_list == ["http://one.test", "http://two.test"]


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=70_000)


def test_log_path_is_derived_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        log_dir=tmp_path,
        log_file_name="test.log",
    )

    assert settings.log_file_path == tmp_path / "test.log"
