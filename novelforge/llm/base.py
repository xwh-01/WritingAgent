"""Abstract language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    @abstractmethod
    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return the assistant content for a chat completion."""
