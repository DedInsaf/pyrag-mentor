"""Domain-specific exceptions used across backend layers."""


class PyRAGMentorError(Exception):
    """Base class for expected application errors."""


class ConfigurationError(PyRAGMentorError):
    """Raised when required application configuration is invalid or missing."""


class ExternalServiceError(PyRAGMentorError):
    """Raised when an external infrastructure service is unavailable."""


class LLMServiceError(ExternalServiceError):
    """Raised when an LLM request fails or returns an invalid response."""


class RetrievalError(PyRAGMentorError):
    """Raised when knowledge retrieval cannot be completed."""


class AnswerValidationError(PyRAGMentorError):
    """Raised when a generated answer violates validation rules."""
