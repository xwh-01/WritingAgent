"""DeepSeek adapter compatible with the OpenAI Python SDK."""

from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from novelforge.core.exceptions import ConfigurationError
from novelforge.llm.base import LLMClient, LLMResponse


class ProviderError(RuntimeError):
    """LLM 提供商调用失败的异常，附带提供商名称和重试次数。"""

    def __init__(self, message: str, provider: str = "deepseek", attempts: int = 0):
        super().__init__(message)
        self.error_type = "provider_call_failed"
        self.provider = provider
        self.attempts = attempts


class DeepSeekClient(LLMClient):
    """基于 OpenAI SDK 的 DeepSeek API 客户端，支持自动重试和指数退避。"""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ):
        """初始化 OpenAI 客户端，校验 API Key 并设置超时与重试参数。"""
        if not api_key:
            raise ConfigurationError("DEEPSEEK_API_KEY is required when provider is deepseek.")
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.call_history: list[LLMResponse] = []

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """发送聊天补全请求，失败时进行指数退避重试，全部失败后抛出 ProviderError。"""
        return self.chat_completion_result(messages, **kwargs).content

    def chat_completion_result(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> LLMResponse:
        """Send a request and preserve provider evidence needed by live evaluations."""
        last_error: Exception | None = None
        started = time.perf_counter()
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs.setdefault("timeout", self.timeout)
                kwargs.setdefault("temperature", self.temperature)
                kwargs.setdefault("max_tokens", self.max_tokens)
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages, **kwargs
                )
                choice = response.choices[0]
                usage = getattr(response, "usage", None)
                result = LLMResponse(
                    content=choice.message.content or "",
                    provider="deepseek",
                    model=getattr(response, "model", None) or self.model,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                    finish_reason=getattr(choice, "finish_reason", None),
                    request_id=getattr(response, "id", None),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    attempts=attempt,
                    operation=self._operation(messages),
                )
                self.call_history.append(result)
                return result
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise ProviderError(
            f"DeepSeek provider call failed after {self.max_retries} attempts: {last_error}",
            attempts=self.max_retries,
        ) from last_error

    @staticmethod
    def _operation(messages: list[dict[str, str]]) -> str:
        """Classify calls for cost telemetry without retaining prompt contents."""
        user = messages[-1].get("content", "") if messages else ""
        markers = (
            ("generate_outline", "outline"),
            ("generate_chapter_contract", "chapter_contract"),
            ("generate_beats", "scene_plan"),
            ("scene_end_state_reconcile", "scene_state_reconcile"),
            ("scene_contract_repair", "scene_contract_repair"),
            ("scene_quality_patch", "scene_quality_patch"),
            ("scene_candidate_selection", "scene_candidate_selection"),
            ("SCENE_BRIEF", "scene_draft"),
            ("chapter_contract_semantic_validation", "contract_semantic_review"),
            ("unified_generation_review", "unified_generation_review"),
            ("quality_scorecard_review", "quality_review"),
            ("continuity_audit", "continuity_review"),
            ("continuity_patch_audit", "local_continuity_review"),
        )
        for marker, operation in markers:
            if marker in user:
                return operation
        if "JSON Schema" in user or "JSON Schema" in "\n".join(
            message.get("content", "") for message in messages
        ):
            return "structured_output_repair"
        return "unclassified"
