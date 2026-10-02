"""Fast, offline checks for the stage-one development environment."""

from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path

REQUIRED_PACKAGES = (
    "fastapi",
    "httpx",
    "pydantic_settings",
    "sqlalchemy",
    "celery",
    "redis",
    "qdrant_client",
    "rank_bm25",
)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    errors: list[str] = []

    print(f"Python: {platform.python_version()}")
    print(f"Project: {project_root}")

    if sys.version_info[:2] != (3, 12):
        errors.append("Нужен Python 3.12.x")

    missing = [
        package
        for package in REQUIRED_PACKAGES
        if importlib.util.find_spec(package) is None
    ]
    if missing:
        errors.append("Не установлены пакеты: " + ", ".join(missing))

    env_file = project_root / ".env"
    if not env_file.exists():
        errors.append("Не найден .env: скопируйте .env.example в .env")

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1

    print("[OK] Окружение этапа 1 готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
