"""Abstract language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    """Provider-neutral response metadata used by real evaluations and tracing."""

    content: str
    provider: str = "unknown"
    model: str = "unknown"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None
    attempts: int = 1
    operation: str = "unknown"


class LLMClient(ABC):
    """LLM 客户端的抽象接口，所有具体实现需提供 chat_completion 方法。"""

    @abstractmethod
    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return the assistant content for a chat completion."""

    def chat_completion_result(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> LLMResponse:
        """Return content plus metadata, with compatibility for simple clients."""
        return LLMResponse(content=self.chat_completion(messages, **kwargs))
