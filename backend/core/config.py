"""Typed application settings loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.constants import DEFAULT_CORS_ORIGINS, LLMProvider


class Settings(BaseSettings):
    """Central configuration for the API and future infrastructure services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = Field(default="PyRAG Mentor", validation_alias="PROJECT_NAME")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias="API_PORT")
    api_reload: bool = Field(default=False, validation_alias="API_RELOAD")
    cors_origins: str = Field(
        default=",".join(DEFAULT_CORS_ORIGINS),
        validation_alias="CORS_ORIGINS",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./pyrag_mentor.db",
        validation_alias="DATABASE_URL",
    )

    llm_provider: LLMProvider = Field(
        default=LLMProvider.YANDEX_GPT,
        validation_alias="LLM_PROVIDER",
    )
    fallback_to_huggingface: bool = Field(
        default=True,
        validation_alias="FALLBACK_TO_HUGGINGFACE",
    )
    yandex_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="YANDEX_API_KEY",
    )
    yandex_folder_id: str | None = Field(
        default=None,
        validation_alias="YANDEX_FOLDER_ID",
    )
    yandex_gpt_model: str = Field(
        default="yandexgpt/latest",
        validation_alias="YANDEX_GPT_MODEL",
    )
    yandex_gpt_endpoint: str = Field(
        default="https://ai.api.cloud.yandex.net/foundationModels/v1/completion",
        validation_alias="YANDEX_GPT_ENDPOINT",
    )
    yandex_gpt_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        validation_alias="YANDEX_GPT_TEMPERATURE",
    )
    yandex_gpt_max_tokens: int = Field(
        default=2000,
        ge=1,
        validation_alias="YANDEX_GPT_MAX_TOKENS",
    )
    hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")
    hf_model: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct",
        validation_alias="HF_MODEL",
    )

    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        validation_alias="EMBEDDING_MODEL",
    )
    qdrant_host: str = Field(default="localhost", validation_alias="QDRANT_HOST")
    qdrant_port: int = Field(
        default=6333,
        ge=1,
        le=65535,
        validation_alias="QDRANT_PORT",
    )
    qdrant_collection_name: str = Field(
        default="python_docs",
        validation_alias="QDRANT_COLLECTION_NAME",
    )
    rrf_k: int = Field(default=60, ge=1, validation_alias="RRF_K")
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )

    jwt_secret_key: SecretStr = Field(
        default=SecretStr("replace_with_a_long_random_string"),
        validation_alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiration_minutes: int = Field(
        default=10080,
        ge=1,
        validation_alias="JWT_EXPIRATION_MINUTES",
    )

    max_agent_iterations: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias="MAX_AGENT_ITERATIONS",
    )
    critic_success_score: float = Field(
        default=7.0,
        ge=0.0,
        le=10.0,
        validation_alias="CRITIC_SUCCESS_SCORE",
    )

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_dir: Path = Field(default=Path("logs"), validation_alias="LOG_DIR")
    log_file_name: str = Field(
        default="pyrag-mentor.log",
        validation_alias="LOG_FILE_NAME",
    )
    log_max_bytes: int = Field(
        default=5_000_000,
        ge=1024,
        validation_alias="LOG_MAX_BYTES",
    )
    log_backup_count: int = Field(
        default=5,
        ge=1,
        validation_alias="LOG_BACKUP_COUNT",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate the standard logging level."""

        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        """Return normalized origins suitable for FastAPI CORSMiddleware."""

        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def log_file_path(self) -> Path:
        """Return the configured rotating log file path."""

        return self.log_dir / self.log_file_name


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the application process."""

    return Settings()
