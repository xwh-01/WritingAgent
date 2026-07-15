"""Common agent utilities."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from novelforge.core.utils import extract_json
from novelforge.llm.base import LLMClient

TModel = TypeVar("TModel", bound=BaseModel)


class BaseAgent:
    """Agent 基类，提供 LLM 交互与 JSON 解析的通用能力。"""

    name = "base"

    def __init__(self, llm: LLMClient):
        """初始化 Agent，绑定 LLM 客户端。"""
        self.llm = llm

    def _chat(self, system: str, user: str, **kwargs: Any) -> str:
        """向 LLM 发送 system + user 消息，返回回复文本。"""
        return self.llm.chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **kwargs,
        )

    def _parse_model_list(self, text: str, model: type[TModel]) -> list[TModel]:
        """将 LLM 返回文本解析为指定 Pydantic 模型的列表。"""
        data = extract_json(text)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list for {model.__name__}.")
        return [model.model_validate(item) for item in data]

    def _parse_model(self, text: str, model: type[TModel]) -> TModel:
        """将 LLM 返回文本解析为指定 Pydantic 模型的单个实例。"""
        return model.model_validate(extract_json(text))
