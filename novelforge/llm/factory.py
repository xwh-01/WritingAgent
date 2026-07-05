"""Factory for configured LLM clients."""

from __future__ import annotations

from novelforge.core.config import LLMConfig
from novelforge.llm.base import LLMClient
from novelforge.llm.mock_client import MockLLMClient


def build_llm_client(config: LLMConfig) -> LLMClient:
    provider = config.provider.lower()
    if provider == "deepseek":
        from novelforge.llm.deepseek_client import DeepSeekClient

        return DeepSeekClient(api_key=config.api_key, model=config.model, base_url=config.base_url)
    if provider in {"mock", "local", "fake"}:
        return MockLLMClient()
    raise ValueError(f"Unsupported LLM provider: {config.provider}")
