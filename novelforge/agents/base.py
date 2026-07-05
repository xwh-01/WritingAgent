"""Common agent utilities."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from novelforge.llm.base import LLMClient

TModel = TypeVar("TModel", bound=BaseModel)


class BaseAgent:
    name = "base"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _chat(self, system: str, user: str, **kwargs: Any) -> str:
        return self.llm.chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **kwargs,
        )

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(1))

    def _parse_model_list(self, text: str, model: type[TModel]) -> list[TModel]:
        data = self._extract_json(text)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list for {model.__name__}.")
        return [model.model_validate(item) for item in data]

    def _parse_model(self, text: str, model: type[TModel]) -> TModel:
        return model.model_validate(self._extract_json(text))
