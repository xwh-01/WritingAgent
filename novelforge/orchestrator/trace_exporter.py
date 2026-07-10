"""Export agent traces as JSON payloads or compact Markdown reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def trace_to_json(run) -> dict[str, Any]:
    """将运行对象序列化为 JSON 兼容字典，确保包含 trace_events 键。"""
    payload = run.model_dump() if hasattr(run, "model_dump") else dict(run)
    payload.setdefault("trace_events", [])
    return payload


def write_trace_json(run, output_path: str | Path) -> Path:
    """将运行轨迹序列化为 JSON 文件写入磁盘，返回输出路径。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace_to_json(run), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def render_debug_report(run) -> str:
    """将运行轨迹渲染为人类可读的 Markdown 调试报告字符串。"""
    data = trace_to_json(run)
    events = data.get("trace_events") or []
    steps = data.get("steps") or []
    lines = [
        f"# Agent Debug Report: {data.get('id', data.get('run_id', 'unknown'))}",
        "",
        "## Run",
        "",
        f"- Story ID: `{data.get('story_id', '')}`",
        f"- Status: `{data.get('status', '')}`",
        f"- User Message: {data.get('user_message', data.get('objective', ''))}",
        f"- Summary: {data.get('final_summary', data.get('summary', ''))}",
        "",
        "## Steps",
        "",
    ]
    if events:
        for index, event in enumerate(events, 1):
            lines.extend(_format_event(index, event))
    elif steps:
        for index, step in enumerate(steps, 1):
            event = {
                "stage": "director_step",
                "action": step.get("selected_tool", ""),
                "selected_tool": step.get("selected_tool", ""),
                "tool_args": step.get("tool_args", {}),
                "observation": step.get("observation", ""),
                "success": step.get("success", True),
                "error_message": step.get("error", ""),
            }
            lines.extend(_format_event(index, event))
    else:
        lines.append("No trace events recorded.")
    return "\n".join(lines) + "\n"


def write_debug_report(run, output_path: str | Path) -> Path:
    """将调试报告写入 Markdown 文件，返回输出路径。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_debug_report(run), encoding="utf-8")
    return path


def _format_event(index: int, event: dict[str, Any]) -> list[str]:
    """将单条事件字典格式化为 Markdown 段落列表（含工具、评分、耗时、错误等信息）。"""
    score_before = event.get("review_score_before")
    score_after = event.get("review_score_after")
    score_text = ""
    if score_before is not None or score_after is not None:
        score_text = f"score `{score_before}` -> `{score_after}`"
    error_type = event.get("error_type") or ""
    error_message = event.get("error_message") or ""
    return [
        f"### {index}. {event.get('stage', '')} / {event.get('action', '')}",
        "",
        f"- Tool: `{event.get('selected_tool', '')}`",
        f"- Args: `{json.dumps(event.get('tool_args', {}), ensure_ascii=False)}`",
        f"- Success: `{event.get('success', True)}`",
        f"- Memory Hits: `{event.get('memory_hits_count', 0)}`",
        f"- Review Score: {score_text or '`N/A`'}",
        f"- Duration: `{event.get('duration_ms', 0)}ms`",
        f"- Error: `{error_type}` {error_message}",
        f"- Observation: {event.get('observation', '') or event.get('output_summary', '')}",
        "",
    ]
