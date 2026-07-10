"""Factory for configured LLM clients."""

from __future__ import annotations

from novelforge.core.config import LLMConfig
from novelforge.llm.base import LLMClient
from novelforge.llm.mock_client import MockLLMClient


def build_llm_client(config: LLMConfig) -> LLMClient:
    """根据配置中的 provider 字段创建对应的 LLM 客户端实例（deepseek 或 mock）。"""
    provider = config.provider.lower()
    if provider == "deepseek":
        from novelforge.llm.deepseek_client import DeepSeekClient

        return DeepSeekClient(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff_seconds=config.retry_backoff_seconds,
        )
    if provider in {"mock", "local", "fake"}:
        return MockLLMClient()
    raise ValueError(f"Unsupported LLM provider: {config.provider}")
