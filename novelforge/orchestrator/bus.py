"""A tiny synchronous event bus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._handlers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        for handler in self._handlers.get(event_name, []):
            handler(payload or {})
