"""Development entry point for the PyRAG Mentor API."""

import uvicorn

from backend.core.config import get_settings


def main() -> None:
    """Run Uvicorn with values loaded from environment variables."""

    settings = get_settings()
    uvicorn.run(
        "backend.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_config=None,
    )


if __name__ == "__main__":
    main()
