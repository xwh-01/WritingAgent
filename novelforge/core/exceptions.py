"""Domain exceptions used across NovelForge."""


class NovelForgeError(Exception):
    """Base exception for all NovelForge errors."""


class ConfigurationError(NovelForgeError):
    """Raised when configuration is invalid or incomplete."""


class LLMError(NovelForgeError):
    """Raised when an LLM provider call fails."""


class WorkflowError(NovelForgeError):
    """Raised when a workflow transition is invalid."""


class ConcurrentUpdateError(WorkflowError):
    """Raised when a stale Story snapshot attempts to overwrite newer canon."""


class GenerationRejected(WorkflowError):
    """Raised when a generated candidate exhausts repair attempts without passing gates."""

    def __init__(
        self,
        message: str,
        report: object | None = None,
        story: object | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report
        self.story = story
