"""A tiny synchronous event bus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """轻量同步事件总线，支持按事件名注册处理函数和广播事件载荷。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """注册一个事件处理函数，当指定事件名被触发时调用。"""
        self._handlers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """触发事件，依次调用所有已注册的该事件处理函数，传入载荷字典。

        每个 handler 的异常被隔离——某个 handler 失败不影响后续 handler。
        """
        payload = payload or {}
        for handler in self._handlers.get(event_name, []):
            try:
                handler(payload)
            except Exception:
                # Isolate handler failures so one bad subscriber does not
                # break subsequent handlers or the caller.
                pass
