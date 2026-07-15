"""Typed configuration loaded from YAML and environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "mock"
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    timeout: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.0)


class IndexBackendConfig(BaseModel):
    vector_store: Literal["chroma", "in_memory"] = "chroma"
    graph_store: Literal["networkx"] = "networkx"
    text_store: Literal["sqlite_fts"] = "sqlite_fts"


class StorageConfig(BaseModel):
    """One canonical database, one artifact root, and three disposable indexes."""

    database_path: str = "./.data/novelforge/novelforge.db"
    artifact_directory: str = "./.data/novelforge/artifacts"
    vector_index_directory: str = "./.data/novelforge/indexes/chroma"
    graph_index_directory: str = "./.data/novelforge/indexes/graph"
    full_text_index_path: str = "./.data/novelforge/indexes/fts.sqlite3"


class StoryConfig(BaseModel):
    default_chapters: int = Field(default=10, ge=1)
    max_context_tokens: int = Field(default=6000, ge=512)
    auto_polish_drafts: bool = True
    prose_target_words: int = Field(default=1800, ge=100)


class GenerationConfig(BaseModel):
    """Hard acceptance policy for machine-generated prose."""

    min_quality_score: float = Field(default=7.5, ge=0.0, le=10.0)
    max_repairs: int = Field(default=2, ge=0, le=10)
    require_contract_pass: bool = True
    require_continuity_pass: bool = True


class RetrievalConfig(BaseModel):
    type_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "character_state": 6.5,
            "foreshadowing": 6.0,
            "timeline_event": 4.0,
            "world": 3.0,
            "character": 3.0,
            "chapter_summary": 2.0,
        }
    )
    recency_max: float = 5.0
    recency_decay_base: float = 20.0
    entity_match_bonus: float = 7.0
    query_match_bonus_per_term: float = 2.0
    query_match_max: float = 8.0


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    indexes: IndexBackendConfig = Field(default_factory=IndexBackendConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    story: StoryConfig = Field(default_factory=StoryConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


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
    file_data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as stream:
            file_data = yaml.safe_load(stream) or {}

    environment = {
        "llm": {
            "provider": os.getenv("NOVELFORGE_LLM_PROVIDER"),
            "model": os.getenv("NOVELFORGE_LLM_MODEL"),
            "temperature": os.getenv("NOVELFORGE_LLM_TEMPERATURE"),
            "max_tokens": os.getenv("NOVELFORGE_LLM_MAX_TOKENS"),
            "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"),
            "base_url": os.getenv("NOVELFORGE_LLM_BASE_URL"),
            "timeout": os.getenv("NOVELFORGE_LLM_TIMEOUT"),
            "max_retries": os.getenv("NOVELFORGE_LLM_MAX_RETRIES"),
            "retry_backoff_seconds": os.getenv("NOVELFORGE_LLM_RETRY_BACKOFF_SECONDS"),
        },
        "storage": {
            "database_path": os.getenv("NOVELFORGE_DATABASE_PATH"),
            "artifact_directory": os.getenv("NOVELFORGE_ARTIFACT_DIR"),
            "vector_index_directory": os.getenv("NOVELFORGE_CHROMA_DIR"),
            "graph_index_directory": os.getenv("NOVELFORGE_GRAPH_DIR"),
            "full_text_index_path": os.getenv("NOVELFORGE_FTS_PATH"),
        },
        "indexes": {
            "vector_store": os.getenv("NOVELFORGE_VECTOR_BACKEND"),
            "graph_store": os.getenv("NOVELFORGE_GRAPH_BACKEND"),
            "text_store": os.getenv("NOVELFORGE_TEXT_BACKEND"),
        },
        "logging": {"level": os.getenv("NOVELFORGE_LOG_LEVEL")},
    }
    cleaned = {
        section: {key: value for key, value in values.items() if value is not None}
        for section, values in environment.items()
        if any(value is not None for value in values.values())
    }
    return AppConfig.model_validate(_deep_merge(file_data, cleaned))


__all__ = [
    "AppConfig",
    "GenerationConfig",
    "IndexBackendConfig",
    "LLMConfig",
    "LoggingConfig",
    "RetrievalConfig",
    "StorageConfig",
    "StoryConfig",
    "load_config",
]
