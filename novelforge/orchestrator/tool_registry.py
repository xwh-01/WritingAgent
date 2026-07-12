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
    """工具规格的不可变数据类，定义工具名称、描述、参数模式和处理器。"""
    name: str
    description: str
    args_schema: dict[str, str]
    args_model: type[BaseModel]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    """导演智能体的工具注册中心，注册引擎操作作为可调用工具，支持参数校验和轨迹记录。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self._tools: dict[str, ToolSpec] = {}
        self._register_defaults()

    def list_specs(self) -> list[dict[str, Any]]:
        """返回所有已注册工具的列表，含名称、描述和 JSON Schema。"""
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
        """检查指定名称的工具是否已注册。"""
        return name in self._tools

    def execute(self, name: str, args: dict[str, Any] | None = None, run_id: str = "") -> dict[str, Any]:
        """执行指定工具：校验参数、调用处理器、记录轨迹，返回统一格式的结果字典。"""
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
        """向注册中心添加一个新工具。"""
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
        """构造工具执行失败的标准化错误结果字典。"""
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
        """根据工具调用结果构造一条标准化的轨迹事件字典。"""
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
        self._register("inspect_chapter", "Read an existing chapter, its version, status, summary, and optionally full content.", {"chapter_index": "int", "include_content": "bool optional"}, self._inspect_chapter)
        self._register("create_outline", "Create or extend chapter outlines.", {"num_chapters": "int optional"}, self._create_outline)
        self._register("create_beats", "Create scene beats for a chapter.", {"chapter_index": "int"}, self._create_beats)
        self._register("write_chapter", "Write a draft chapter.", {"chapter_index": "int"}, self._write_chapter)
        self._register("review_chapter", "Review a chapter for logic, character, and pacing issues.", {"chapter_index": "int"}, self._review_chapter)
        self._register("revise_chapter", "Create a reviewed revision proposal for an existing chapter. It never overwrites正文 before user approval.", {"chapter_index": "int", "revision_instruction": "str optional", "revised_content": "str optional"}, self._revise_chapter)
        self._register("auto_write_chapter", "Write, review, revise, and re-review a chapter.", {"chapter_index": "int"}, self._auto_write_chapter)
        self._register("audit_continuity", "Audit long-form continuity for a chapter.", {"chapter_index": "int"}, self._audit_continuity)
        self._register("analyze_character_continuity", "Analyze one character's persona, knowledge, emotion, location, and relationships across a chapter range; return evidence-backed repair targets.", {"character": "str", "start_chapter": "int", "end_chapter": "int"}, self._analyze_character_continuity)
        self._register("update_memory", "Re-index and extract long-form memory for a chapter.", {"chapter_index": "int"}, self._update_memory)
        self._register("list_foreshadowings", "List foreshadowings, optionally filtered by status.", {"status": "str optional"}, self._list_foreshadowings)

    def _story(self):
        """获取引擎中当前活动故事对象的便捷方法。"""
        return self.engine._require_story()

    def _chapter_index(self, args: dict[str, Any]) -> int:
        """从工具参数中提取 chapter_index，默认使用当前章节，校验为整数后返回。"""
        value = args.get("chapter_index")
        if value is None:
            story = self._story()
            value = story.current_chapter or 1
        try:
            return int(value)
        except Exception as exc:
            raise WorkflowError("chapter_index must be an integer.") from exc

    def _show_status(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：显示当前故事的进度摘要（标题、章节数、角色数、记忆卡数等）。"""
        story = self._story()
        data = {
            "story_id": str(story.id),
            "title": story.title,
            "status": story.status,
            "current_chapter": story.current_chapter,
            "outlines": len(story.content.outlines),
            "chapters": len(story.content.chapters),
            "characters": len(story.content.characters),
            "memory_cards": len(story.memory.cards),
            "foreshadowings": len(story.memory.foreshadowings),
            "chapter_versions": {str(index): chapter.version for index, chapter in story.content.chapters.items()},
            "pending_foreshadowings": [
                item.model_dump() for item in story.memory.foreshadowings if item.status == "pending"
            ][:12],
            "recent_character_facts": [item.model_dump() for item in story.memory.facts[-20:]],
            "open_revision_proposals": [
                item.model_dump(exclude={"original_content", "proposed_content"})
                for item in story.quality.revision_proposals if item.status == "awaiting_approval"
            ],
        }
        return {"observation": f"{story.title}: ch{story.current_chapter}, {len(story.content.chapters)} drafted, {len(story.memory.foreshadowings)} foreshadowings.", "data": data}

    def _create_outline(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：创建或扩展章节大纲。"""
        story = self._story()
        num_chapters = int(args.get("num_chapters") or max(len(story.content.outlines), story.current_chapter, 1) or self.engine.config.story.default_chapters)
        outlines = self.engine.generate_outline(num_chapters)
        return {"observation": f"Created outline with {len(outlines)} chapters.", "data": [item.model_dump() for item in outlines]}

    def _inspect_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：读取章节事实，不修改任何项目状态。"""
        chapter_index = self._chapter_index(args)
        chapter = self._story().content.chapters.get(chapter_index)
        if chapter is None:
            raise WorkflowError(f"Chapter {chapter_index} does not exist.")
        data = chapter.model_dump()
        if not args.get("include_content", True):
            data["content"] = ""
            data["history"] = []
        return {
            "observation": f"Inspected chapter {chapter_index} v{chapter.version} ({len(chapter.content)} chars).",
            "data": data,
        }

    def _create_beats(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：为指定章节生成场景节拍。"""
        chapter = self.engine.generate_beats(self._chapter_index(args))
        return {"observation": f"Created {len(chapter.beats)} beats for chapter {chapter.index}.", "data": chapter.model_dump()}

    def _write_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：撰写指定章节的草稿内容。"""
        chapter = self.engine.write_chapter(self._chapter_index(args))
        return {"observation": f"Wrote chapter {chapter.index}: {chapter.title} ({len(chapter.content)} chars).", "data": chapter.model_dump()}

    def _review_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：对指定章节执行逻辑、角色和节奏评审。"""
        chapter_index = self._chapter_index(args)
        report = self.engine.request_review(chapter_index)
        issue_count = len(report.logic_issues) + len(report.character_issues) + len(report.pacing_issues)
        return {"observation": f"Reviewed chapter {chapter_index}: {issue_count} issues, verdict={report.verdict}.", "data": report.model_dump()}

    def _revise_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：基于最新评审报告或手动提供的修订内容修改章节。"""
        instruction = args.get("revision_instruction") or "根据最新审查报告修改本章"
        proposal = self.engine.create_revision_proposal(self._chapter_index(args), instruction)
        return {
            "observation": (
                f"Created revision proposal {proposal.id} for chapter {proposal.chapter_index}; "
                "waiting for user approval before changing the chapter."
            ),
            "data": proposal.model_dump(),
            "requires_approval": True,
        }

    def _auto_write_chapter(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：对指定章节执行写作→评审→修订自动化循环。"""
        chapter_index = self._chapter_index(args)
        report = self.engine.auto_write_chapter(chapter_index)
        return {
            "observation": f"Auto-wrote chapter {chapter_index}: score={report.final_score:.2f}, passed={report.passed}.",
            "data": report.model_dump(),
            "review_score_after": report.final_score,
        }

    def _audit_continuity(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：审计指定章节的长篇连续性。"""
        chapter_index = self._chapter_index(args)
        report = self.engine.audit_chapter_continuity(chapter_index)
        return {"observation": f"Audited chapter {chapter_index}: risk={report.risk_score:.1f}, passed={report.passed}.", "data": report.model_dump()}

    def _analyze_character_continuity(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：审计角色弧线并返回需要修订的章节和证据。"""
        report = self.engine.audit_character_continuity(
            str(args["character"]),
            int(args["start_chapter"]),
            int(args["end_chapter"]),
        )
        return {
            "observation": (
                f"Audited {report.character_name or report.character_id} across chapters "
                f"{report.start_chapter}-{report.end_chapter}: {len(report.issues)} issue(s), "
                f"repair targets={report.affected_chapters}."
            ),
            "data": report.model_dump(),
            "repair_targets": report.affected_chapters,
        }

    def _update_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：重新索引指定章节的记忆数据（角色、世界观）并审计连续性。"""
        story = self._story()
        chapter_index = self._chapter_index(args)
        chapter = story.content.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no content to update memory from.")
        self.engine._process_chapter_memory(story, chapter)
        story.touch()
        self.engine.save_state()
        return {
            "observation": f"Updated memory for chapter {chapter_index}: {len(story.memory.cards)} cards, {len(story.memory.chapter_summaries)} summaries.",
            "data": {"memory_cards": len(story.memory.cards), "chapter_summaries": len(story.memory.chapter_summaries)},
        }

    def _list_foreshadowings(self, args: dict[str, Any]) -> dict[str, Any]:
        """工具：列出故事中的伏笔条目，可按状态筛选。"""
        story = self._story()
        status = args.get("status")
        items = story.memory.foreshadowings
        if status:
            items = [item for item in items if item.status == status]
        return {
            "observation": f"Found {len(items)} foreshadowings" + (f" with status={status}." if status else "."),
            "data": [item.model_dump() for item in items],
        }
