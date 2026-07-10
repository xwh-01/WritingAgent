"""Abstract language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """LLM 客户端的抽象接口，所有具体实现需提供 chat_completion 方法。"""

    @abstractmethod
    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return the assistant content for a chat completion."""
