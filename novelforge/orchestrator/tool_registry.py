"""Tool registry used by director-style agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from novelforge.core.exceptions import WorkflowError
from novelforge.orchestrator.tool_schemas import TOOL_ARG_SCHEMAS
from novelforge.orchestrator.trace import (
    ERROR_TOOL_ARG_INVALID,
    classify_exception,
    trace_timer,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: dict[str, str]
    args_model: type[BaseModel]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._tools: dict[str, ToolSpec] = {}
        self._register_defaults()

    def list_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "args_schema": tool.args_schema,
                "json_schema": tool.args_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, args: dict[str, Any] | None = None, run_id: str = "") -> dict[str, Any]:
        args = args or {}
        if name not in self._tools:
            return self._error_result(name, args, ERROR_TOOL_ARG_INVALID, f"Unknown director tool: {name}", run_id)
        tool = self._tools[name]
        try:
            validated = tool.args_model.model_validate(args).model_dump(exclude_none=True)
        except ValidationError as exc:
            return self._error_result(name, args, ERROR_TOOL_ARG_INVALID, str(exc), run_id)
        with trace_timer() as timer:
            try:
                result = tool.handler(validated)
            except Exception as exc:
                return self._error_result(name, validated, classify_exception(exc), str(exc), run_id, timer.duration_ms)
        observation = str(result.get("observation") or result)
        result.setdefault("success", True)
        result.setdefault("error_type", "")
        result.setdefault("error_message", "")
        result.setdefault("selected_tool", name)
        result.setdefault("tool_args", validated)
        result.setdefault("duration_ms", timer.duration_ms)
        result.setdefault("output_summary", observation)
        result.setdefault("trace_event", self._trace_event(name, validated, result, run_id, timer.duration_ms))
        return result

    def _register(self, name: str, description: str, args_schema: dict[str, str], handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            args_schema=args_schema,
            args_model=TOOL_ARG_SCHEMAS[name],
            handler=handler,
        )

    def _error_result(
        self,
        name: str,
        args: dict[str, Any],
        error_type: str,
        error_message: str,
        run_id: str,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        result = {
            "success": False,
            "selected_tool": name,
            "tool_args": args,
            "observation": f"{error_type}: {error_message}",
            "output_summary": "",
            "error_type": error_type,
            "error_message": error_message,
            "duration_ms": duration_ms,
        }
        result["trace_event"] = self._trace_event(name, args, result, run_id, duration_ms)
        return result

    def _trace_event(self, name: str, args: dict[str, Any], result: dict[str, Any], run_id: str, duration_ms: int) -> dict[str, Any]:
        try:
            story_id = str(self._story().id)
        except Exception:
            story_id = ""
        chapter_index = args.get("chapter_index")
        context_stats = getattr(self.engine.context_assembler, "last_context_stats", {})
        return {
            "run_id": run_id,
            "story_id": story_id,
            "chapter_index": chapter_index if isinstance(chapter_index, int) else None,
            "stage": "tool_call",
            "action": name,
            "selected_tool": name,
            "tool_args": args,
            "input_summary": f"Execute tool {name}",
            "output_summary": str(result.get("output_summary") or result.get("observation") or ""),
            "observation": str(result.get("observation") or ""),
            "memory_hits_count": int(context_stats.get("memory_hits_count", 0) or 0),
            "review_score_after": result.get("review_score_after"),
            "success": bool(result.get("success", True)),
            "error_type": str(result.get("error_type") or ""),
            "error_message": str(result.get("error_message") or ""),
            "duration_ms": duration_ms,
        }

    def _register_defaults(self) -> None:
        self._register("show_status", "Show current story progress, outline count, chapter count, and memory counts.", {}, self._show_status)
        self._register("create_outline", "Create or extend chapter outlines.", {"num_chapters": "int optional"}, self._create_outline)
        self._register("create_beats", "Create scene beats for a chapter.", {"chapter_index": "int"}, self._create_beats)
        self._register("write_chapter", "Write a draft chapter.", {"chapter_index": "int"}, self._write_chapter)
        self._register("review_chapter", "Review a chapter for logic, character, and pacing issues.", {"chapter_index": "int"}, self._review_chapter)
        self._register("revise_chapter", "Revise a chapter using the latest review report or optional revised_content.", {"chapter_index": "int", "revised_content": "str optional"}, self._revise_chapter)
        self._register("auto_write_chapter", "Write, review, revise, and re-review a chapter.", {"chapter_index": "int"}, self._auto_write_chapter)
        self._register("audit_continuity", "Audit long-form continuity for a chapter.", {"chapter_index": "int"}, self._audit_continuity)
        self._register("update_memory", "Re-index and extract long-form memory for a chapter.", {"chapter_index": "int"}, self._update_memory)
        self._register("list_foreshadowings", "List foreshadowings, optionally filtered by status.", {"status": "str optional"}, self._list_foreshadowings)

    def _story(self):
        return self.engine._require_story()

    def _chapter_index(self, args: dict[str, Any]) -> int:
        value = args.get("chapter_index")
        if value is None:
            story = self._story()
            value = story.current_chapter or 1
        try:
            return int(value)
        except Exception as exc:
            raise WorkflowError("chapter_index must be an integer.") from exc

    def _show_status(self, args: dict[str, Any]) -> dict[str, Any]:
        story = self._story()
        data = {
            "story_id": str(story.id),
            "title": story.title,
            "status": story.status,
            "current_chapter": story.current_chapter,
            "outlines": len(story.outlines),
            "chapters": len(story.chapters),
            "characters": len(story.characters),
            "memory_cards": len(story.memory_cards),
            "foreshadowings": len(story.foreshadowings),
        }
        return {"observation": f"{story.title}: ch{story.current_chapter}, {len(story.chapters)} drafted, {len(story.foreshadowings)} foreshadowings.", "data": data}

    def _create_outline(self, args: dict[str, Any]) -> dict[str, Any]:
        story = self._story()
        num_chapters = int(args.get("num_chapters") or max(len(story.outlines), story.current_chapter, 1) or self.engine.config.story.default_chapters)
        outlines = self.engine.generate_outline(num_chapters)
        return {"observation": f"Created outline with {len(outlines)} chapters.", "data": [item.model_dump() for item in outlines]}

    def _create_beats(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = self.engine.generate_beats(self._chapter_index(args))
        return {"observation": f"Created {len(chapter.beats)} beats for chapter {chapter.index}.", "data": chapter.model_dump()}

    def _write_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = self.engine.write_chapter(self._chapter_index(args))
        return {"observation": f"Wrote chapter {chapter.index}: {chapter.title} ({len(chapter.content)} chars).", "data": chapter.model_dump()}

    def _review_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter_index = self._chapter_index(args)
        report = self.engine.request_review(chapter_index)
        issue_count = len(report.logic_issues) + len(report.character_issues) + len(report.pacing_issues)
        return {"observation": f"Reviewed chapter {chapter_index}: {issue_count} issues, verdict={report.verdict}.", "data": report.model_dump()}

    def _revise_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter = self.engine.apply_revision(self._chapter_index(args), args.get("revised_content"))
        return {"observation": f"Revised chapter {chapter.index}: {chapter.title} v{chapter.version}.", "data": chapter.model_dump()}

    def _auto_write_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter_index = self._chapter_index(args)
        report = self.engine.auto_write_chapter(chapter_index)
        return {
            "observation": f"Auto-wrote chapter {chapter_index}: score={report.final_score:.2f}, passed={report.passed}.",
            "data": report.model_dump(),
            "review_score_after": report.final_score,
        }

    def _audit_continuity(self, args: dict[str, Any]) -> dict[str, Any]:
        chapter_index = self._chapter_index(args)
        report = self.engine.audit_chapter_continuity(chapter_index)
        return {"observation": f"Audited chapter {chapter_index}: risk={report.risk_score:.1f}, passed={report.passed}.", "data": report.model_dump()}

    def _update_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        story = self._story()
        chapter_index = self._chapter_index(args)
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no content to update memory from.")
        self.engine._process_chapter_memory(story, chapter)
        story.touch()
        self.engine.save_state()
        return {
            "observation": f"Updated memory for chapter {chapter_index}: {len(story.memory_cards)} cards, {len(story.chapter_summaries)} summaries.",
            "data": {"memory_cards": len(story.memory_cards), "chapter_summaries": len(story.chapter_summaries)},
        }

    def _list_foreshadowings(self, args: dict[str, Any]) -> dict[str, Any]:
        story = self._story()
        status = args.get("status")
        items = story.foreshadowings
        if status:
            items = [item for item in items if item.status == status]
        return {
            "observation": f"Found {len(items)} foreshadowings" + (f" with status={status}." if status else "."),
            "data": [item.model_dump() for item in items],
        }
