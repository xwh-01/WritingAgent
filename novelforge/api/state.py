"""Shared API engine registry."""

from __future__ import annotations

from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.orchestrator.job_registry import AutoRevisionJobRegistry

ENGINES: dict[str, NovelForgeEngine] = {}
AUTO_REVISION_JOBS = AutoRevisionJobRegistry()


def get_engine(story_id: str) -> NovelForgeEngine:
    """根据故事 ID 获取或创建对应的 NovelForgeEngine 实例，并缓存在全局字典中。"""
    engine = ENGINES.get(story_id)
    if engine is not None:
        return engine
    engine = NovelForgeEngine()
    engine.load_state(story_id)
    ENGINES[story_id] = engine
    return engine
