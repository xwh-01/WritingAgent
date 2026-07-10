"""Configuration loader using YAML with environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM 提供商配置，含模型名、温度、Token 上限、API 地址及重试策略。"""

    provider: str = "mock"
    model: str = "deepseek-chat"
    temperature: float = 0.8
    max_tokens: int = 4096
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    timeout: float = 60.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0


class MemoryConfig(BaseModel):
    """记忆存储配置，指定向量库、图库、全文索引后端及持久化路径。"""

    vector_store: str = "chroma"
    graph_store: str = "networkx"
    text_store: str = "sqlite_fts"
    persist_directory: str = "./novelforge/storage/chroma_data"
    graph_directory: str = "./novelforge/storage/graph_data"
    sqlite_path: str = "./novelforge/storage/story_state/fts.sqlite3"


class StoryConfig(BaseModel):
    """故事生成相关配置，含默认章节数、上下文 Token 上限及草稿润色开关。"""

    default_chapters: int = 10
    max_context_tokens: int = 6000
    history_limit: int = 20
    auto_polish_drafts: bool = True
    prose_target_words: int = 1800


class LoggingConfig(BaseModel):
    """日志配置，控制日志输出级别。"""

    level: str = "INFO"


class AutoRevisorConfig(BaseModel):
    """自动修订器配置，设定最大修订轮数、通过阈值和各项质量权重。"""

    max_rounds: int = 5
    pass_threshold: float = 8.5
    score_samples: int = 3
    quality_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "logic_consistency": 0.25,
            "character_fidelity": 0.25,
            "foreshadowing_handling": 0.20,
            "pacing": 0.15,
            "style_uniformity": 0.15,
        }
    )


class MemoryRankerConfig(BaseModel):
    """记忆重排序器配置，定义各类型权重和衰减参数。

    TYPE_WEIGHTS 优先级逻辑：
    - foreshadowing (6.0): 最高——遗忘未回收伏笔导致叙事断裂的风险最大
    - character_state (6.5): 很高——角色状态漂移是长篇写作中最常见的一致性错误
    - causal_event (4.0): 中等——因果链断裂影响逻辑，但出现频率低
    - world / character (3.0): 较低——这些在别处已有冗余检索
    - chapter_summary (2.0): 最低——避免与 rolling context 重复注入
    """

    type_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "foreshadowing": 6.0,
            "character_state": 6.5,
            "causal_event": 4.0,
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


class AppConfig(BaseModel):
    """应用总配置，聚合 LLM、记忆、故事、日志、自动修订和记忆重排序各子配置。"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    story: StoryConfig = Field(default_factory=StoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auto_revisor: AutoRevisorConfig = Field(default_factory=AutoRevisorConfig)
    memory_ranker: MemoryRankerConfig = Field(default_factory=MemoryRankerConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个字典，override 中的值时覆盖 base 中同名键。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载 YAML 配置文件并用环境变量覆盖，返回 AppConfig 实例。"""
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
            "timeout": os.getenv("NOVELFORGE_LLM_TIMEOUT"),
            "max_retries": os.getenv("NOVELFORGE_LLM_MAX_RETRIES"),
            "retry_backoff_seconds": os.getenv("NOVELFORGE_LLM_RETRY_BACKOFF_SECONDS"),
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
