"""Unified trace events for bounded agentic workflows."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from novelforge.core.models import utc_now


ERROR_PROVIDER_CALL_FAILED = "provider_call_failed"
ERROR_TOOL_ARG_INVALID = "tool_arg_invalid"
ERROR_TOOL_EXECUTION_FAILED = "tool_execution_failed"
ERROR_PRECONDITION_MISSING = "precondition_missing"
ERROR_QUALITY_GATE_FAILED = "quality_gate_failed"
ERROR_MEMORY_RECALL_FAILED = "memory_recall_failed"
ERROR_UNKNOWN = "unknown_error"


class AgentTraceEvent(BaseModel):
    """智能体轨迹事件的数据模型，记录单次操作的上下文、结果和耗时。"""

    run_id: str
    story_id: str = ""
    chapter_index: int | None = None
    stage: str = ""
    action: str = ""
    selected_tool: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    input_summary: str = ""
    output_summary: str = ""
    observation: str = ""
    memory_hits_count: int = 0
    review_score_before: float | None = None
    review_score_after: float | None = None
    success: bool = True
    error_type: str = ""
    error_message: str = ""
    duration_ms: int = 0
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class TraceRecorder:
    """轨迹记录器：收集一次运行中的所有 AgentTraceEvent 事件。"""

    def __init__(self, run_id: str, story_id: str = "", chapter_index: int | None = None) -> None:
        self.run_id = run_id
        self.story_id = story_id
        self.chapter_index = chapter_index
        self.events: list[AgentTraceEvent] = []

    def record(self, **kwargs: Any) -> AgentTraceEvent:
        """创建并追加一条轨迹事件到内部列表，自动填充 run_id 等上下文字段。"""
        data = {
            "run_id": self.run_id,
            "story_id": self.story_id,
            "chapter_index": self.chapter_index,
            **kwargs,
        }
        event = AgentTraceEvent(**data)
        self.events.append(event)
        return event


class trace_timer:
    """上下文管理器：记录代码块的执行耗时（毫秒），结果存储在 duration_ms 属性上。"""

    def __enter__(self) -> "trace_timer":
        self._start = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.duration_ms = int((perf_counter() - self._start) * 1000)

    duration_ms: int = 0


def classify_exception(exc: Exception) -> str:
    """根据异常消息中的关键词将异常归类为预定义的错误类型常量。"""
    text = str(exc).lower()
    if "provider" in text or "api" in text or "timeout" in text:
        return ERROR_PROVIDER_CALL_FAILED
    if "chapter_index" in text or "validation" in text or "must be" in text:
        return ERROR_TOOL_ARG_INVALID
    if "outline" in text or "beats" in text or "no draft" in text or "no content" in text:
        return ERROR_PRECONDITION_MISSING
    if "memory" in text:
        return ERROR_MEMORY_RECALL_FAILED
    if "score" in text or "threshold" in text or "quality" in text:
        return ERROR_QUALITY_GATE_FAILED
    return ERROR_TOOL_EXECUTION_FAILED if text else ERROR_UNKNOWN


def is_recoverable(error_type: str) -> bool:
    """判断给定的错误类型是否属于可恢复（非致命）错误。"""
    return error_type in {
        ERROR_TOOL_ARG_INVALID,
        ERROR_PRECONDITION_MISSING,
        ERROR_TOOL_EXECUTION_FAILED,
        ERROR_QUALITY_GATE_FAILED,
        ERROR_MEMORY_RECALL_FAILED,
    }
