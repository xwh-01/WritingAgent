"""Domain exceptions used across NovelForge."""


class NovelForgeError(Exception):
    """Base exception for all NovelForge errors."""


class ConfigurationError(NovelForgeError):
    """Raised when configuration is invalid or incomplete."""


class LLMError(NovelForgeError):
    """Raised when an LLM provider call fails."""


class WorkflowError(NovelForgeError):
    """Raised when a workflow transition is invalid."""


class PersistenceError(NovelForgeError):
    """Raised when story state cannot be saved or loaded."""
