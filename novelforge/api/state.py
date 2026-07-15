"""In-process engine registry for HTTP requests."""

from __future__ import annotations

from novelforge.orchestrator.engine import NovelForgeEngine

ENGINES: dict[str, NovelForgeEngine] = {}


def get_engine(story_id: str) -> NovelForgeEngine:
    engine = ENGINES.get(story_id)
    if engine is None:
        engine = NovelForgeEngine()
        engine.load_state(story_id)
        ENGINES[story_id] = engine
    return engine


__all__ = ["ENGINES", "get_engine"]
