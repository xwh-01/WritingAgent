"""DeepSeek adapter compatible with the OpenAI Python SDK."""

from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from novelforge.core.exceptions import ConfigurationError
from novelforge.llm.base import LLMClient


class ProviderError(RuntimeError):
    def __init__(self, message: str, provider: str = "deepseek", attempts: int = 0):
        super().__init__(message)
        self.error_type = "provider_call_failed"
        self.provider = provider
        self.attempts = attempts


class DeepSeekClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ):
        if not api_key:
            raise ConfigurationError("DEEPSEEK_API_KEY is required when provider is deepseek.")
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs.setdefault("timeout", self.timeout)
                response = self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise ProviderError(f"DeepSeek provider call failed after {self.max_retries} attempts: {last_error}", attempts=self.max_retries) from last_error
