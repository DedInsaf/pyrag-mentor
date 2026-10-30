"""Integration tests for the FastAPI application skeleton."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import Settings
from backend.core.constants import APP_VERSION


def test_healthcheck_returns_service_metadata(tmp_path: Path) -> None:
    settings = Settings(
        project_name="PyRAG Mentor Test",
        log_dir=tmp_path,
        cors_origins="http://localhost:8501",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "PyRAG Mentor Test",
        "version": APP_VERSION,
        "llm_provider": "yandexgpt",
    }


def test_cors_preflight_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        log_dir=tmp_path,
        cors_origins="http://localhost:8501",
    )

    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/healthz",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8501"


def test_database_health_is_healthy(tmp_path: Path) -> None:
    settings = Settings(log_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["services"]["database"]["healthy"] is True
