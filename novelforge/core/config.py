"""Configuration loader using YAML with environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "mock"
    model: str = "deepseek-chat"
    temperature: float = 0.8
    max_tokens: int = 4096
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"


class MemoryConfig(BaseModel):
    vector_store: str = "chroma"
    graph_store: str = "networkx"
    text_store: str = "sqlite_fts"
    persist_directory: str = "./novelforge/storage/chroma_data"
    graph_directory: str = "./novelforge/storage/graph_data"
    sqlite_path: str = "./novelforge/storage/story_state/fts.sqlite3"


class StoryConfig(BaseModel):
    default_chapters: int = 10
    max_context_tokens: int = 6000
    history_limit: int = 20
    auto_polish_drafts: bool = True
    prose_target_words: int = 1800


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AutoRevisorConfig(BaseModel):
    max_rounds: int = 5
    pass_threshold: float = 8.5
    quality_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "logic_consistency": 0.25,
            "character_fidelity": 0.25,
            "foreshadowing_handling": 0.20,
            "pacing": 0.15,
            "style_uniformity": 0.15,
        }
    )


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    story: StoryConfig = Field(default_factory=StoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auto_revisor: AutoRevisorConfig = Field(default_factory=AutoRevisorConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> AppConfig:
    load_dotenv()
    path = Path(config_path or os.getenv("NOVELFORGE_CONFIG", "config.yaml"))
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

    env_data = {
        "llm": {
            "provider": os.getenv("NOVELFORGE_LLM_PROVIDER"),
            "model": os.getenv("NOVELFORGE_LLM_MODEL"),
            "temperature": os.getenv("NOVELFORGE_LLM_TEMPERATURE"),
            "max_tokens": os.getenv("NOVELFORGE_LLM_MAX_TOKENS"),
            "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"),
            "base_url": os.getenv("NOVELFORGE_LLM_BASE_URL"),
        },
        "memory": {
            "persist_directory": os.getenv("NOVELFORGE_CHROMA_DIR"),
            "graph_directory": os.getenv("NOVELFORGE_GRAPH_DIR"),
            "sqlite_path": os.getenv("NOVELFORGE_SQLITE_PATH"),
        },
        "logging": {"level": os.getenv("NOVELFORGE_LOG_LEVEL")},
    }
    cleaned = {
        section: {k: v for k, v in values.items() if v is not None}
        for section, values in env_data.items()
        if any(v is not None for v in values.values())
    }
    merged = _deep_merge(data, cleaned)
    return AppConfig.model_validate(merged)
