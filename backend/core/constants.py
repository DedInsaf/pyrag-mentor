"""Project-wide constants and enumerations."""

from enum import StrEnum

APP_VERSION = "0.5.0"
API_PREFIX = "/api/v1"
HEALTHCHECK_PATH = "/healthz"
SUPPORTED_PYTHON_VERSIONS = ("3.12",)
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:8501",
)
CRITIC_PASS_THRESHOLD = 7.0
ADAPTIVE_BUDGET_LOW = 4.0
ADAPTIVE_BUDGET_MID = 7.0
DEFAULT_GENERATION_SEED = 42


class LLMProvider(StrEnum):
    """Supported text-generation backends."""

    YANDEX_GPT = "yandexgpt"
    HUGGING_FACE = "huggingface"


class RequestType(StrEnum):
    """Question types accepted by the future QA pipeline."""

    QUESTION = "question"
    CODE_REVIEW = "code_review"
    EXPLAIN_ERROR = "explain_error"


class KnowledgeCategory(StrEnum):
    """Top-level categories used to filter the Python knowledge base."""

    LANGUAGE_BASICS = "language_basics"
    STANDARD_LIBRARY = "standard_library"
    ASYNC_PROGRAMMING = "async_programming"
    TESTING = "testing"
    TYPING = "typing"


class UserRole(StrEnum):
    """Application roles reserved for the authentication stage."""

    USER = "user"
    EDITOR = "editor"
    ADMIN = "admin"
