"""DeepSeek adapter compatible with the OpenAI Python SDK."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from novelforge.core.exceptions import ConfigurationError
from novelforge.llm.base import LLMClient


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com"):
        if not api_key:
            raise ConfigurationError("DEEPSEEK_API_KEY is required when provider is deepseek.")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        response = self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        return response.choices[0].message.content or ""
