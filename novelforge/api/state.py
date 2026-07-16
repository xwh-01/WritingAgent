"""In-process engine registry for HTTP requests."""

from __future__ import annotations

import threading

from novelforge.orchestrator.engine import NovelForgeEngine

ENGINES: dict[str, NovelForgeEngine] = {}
_LOCK = threading.RLock()


def get_engine(story_id: str) -> NovelForgeEngine:
    with _LOCK:
        engine = ENGINES.get(story_id)
        if engine is None:
            engine = NovelForgeEngine()
            ENGINES[story_id] = engine
        engine.load_state(story_id)
        return engine


def register_engine(story_id: str, engine: NovelForgeEngine) -> None:
    with _LOCK:
        previous = ENGINES.get(story_id)
        ENGINES[story_id] = engine
    if previous is not None and previous is not engine:
        previous.close()


def remove_engine(story_id: str) -> NovelForgeEngine | None:
    with _LOCK:
        return ENGINES.pop(story_id, None)


def close_all_engines() -> None:
    with _LOCK:
        engines = list(ENGINES.values())
        ENGINES.clear()
    for engine in engines:
        engine.close()


__all__ = ["close_all_engines", "get_engine", "register_engine", "remove_engine"]
