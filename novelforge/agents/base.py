"""Common agent utilities."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from novelforge.core.generation_budget import budgeted_chat_completion
from novelforge.core.utils import extract_json
from novelforge.llm.base import LLMClient

TModel = TypeVar("TModel", bound=BaseModel)


class BaseAgent:
    """Agent 基类，提供 LLM 交互与 JSON 解析的通用能力。"""

    name = "base"
    structured_repair_attempts = 2

    def __init__(self, llm: LLMClient):
        """初始化 Agent，绑定 LLM 客户端。"""
        self.llm = llm

    def _chat(self, system: str, user: str, **kwargs: Any) -> str:
        """向 LLM 发送 system + user 消息，返回回复文本。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return budgeted_chat_completion(self.llm, messages, **kwargs)

    def _parse_model_list(self, text: str, model: type[TModel]) -> list[TModel]:
        """将 LLM 返回文本解析为指定 Pydantic 模型的列表。"""
        data = extract_json(text)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list for {model.__name__}.")
        return [model.model_validate(item) for item in data]

    def _parse_model(self, text: str, model: type[TModel]) -> TModel:
        """将 LLM 返回文本解析为指定 Pydantic 模型的单个实例。"""
        return model.model_validate(extract_json(text))

    def _chat_model(
        self,
        system: str,
        user: str,
        model: type[TModel],
        **kwargs: Any,
    ) -> TModel:
        """Call, validate, then make bounded schema-only repair attempts."""
        raw = self._chat(system, user, **kwargs)
        try:
            return self._parse_model(raw, model)
        except Exception as exc:
            last_raw = raw
            last_error = exc
        for _ in range(self.structured_repair_attempts):
            last_raw = self._repair_structured_output(
                last_raw, model, last_error, is_list=False, **kwargs
            )
            try:
                return self._parse_model(last_raw, model)
            except Exception as exc:
                last_error = exc
        raise last_error

    def _chat_model_list(
        self,
        system: str,
        user: str,
        model: type[TModel],
        **kwargs: Any,
    ) -> list[TModel]:
        """Call, validate, then make bounded schema-only repair attempts on a list."""
        raw = self._chat(system, user, **kwargs)
        try:
            return self._parse_model_list(raw, model)
        except Exception as exc:
            last_raw = raw
            last_error = exc
        for _ in range(self.structured_repair_attempts):
            last_raw = self._repair_structured_output(
                last_raw, model, last_error, is_list=True, **kwargs
            )
            try:
                return self._parse_model_list(last_raw, model)
            except Exception as exc:
                last_error = exc
        raise last_error

    def _repair_structured_output(
        self,
        raw: str,
        model: type[TModel],
        error: Exception,
        *,
        is_list: bool,
        **kwargs: Any,
    ) -> str:
        container = "JSON 数组" if is_list else "JSON 对象"
        system = (
            "你是 JSON 格式修复器。只修复字段类型、枚举值和缺失字段，不增加新事实，"
            f"不输出解释或 Markdown。只输出合法{container}。"
        )
        user = (
            f"校验错误：{error}\n"
            f"目标元素 JSON Schema：{json.dumps(model.model_json_schema(), ensure_ascii=False)}\n"
            f"待修复内容：\n{raw}"
        )
        return self._chat(system, user, **kwargs)
