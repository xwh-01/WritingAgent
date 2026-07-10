"""LLM director agent that chooses tools from live story state."""

from __future__ import annotations

import json
from uuid import uuid4

from novelforge.agents.base import BaseAgent
from novelforge.core.models import AgentDecision, AgentTraceRun, AgentTraceStep, Story, utc_now
from novelforge.orchestrator.trace import (
    ERROR_PRECONDITION_MISSING,
    ERROR_QUALITY_GATE_FAILED,
    ERROR_TOOL_ARG_INVALID,
    ERROR_TOOL_EXECUTION_FAILED,
    AgentTraceEvent,
    classify_exception,
    is_recoverable,
)


class NovelDirectorAgent(BaseAgent):
    """小说导演 Agent，根据故事状态与用户指令选择工具并执行运行循环。"""

    name = "director"

    def run(
        self,
        story_id: str,
        user_message: str,
        max_steps: int,
        story: Story,
        tool_registry,
    ) -> AgentTraceRun:
        """执行导演运行循环：决策 → 执行 → 观察 → 重试/继续，直到完成或失败。"""
        run = AgentTraceRun(id=f"trace-{uuid4().hex[:10]}", story_id=story_id, user_message=user_message)
        recovery_attempts = 0
        forced_decision: AgentDecision | None = None
        for step in range(1, max(1, max_steps) + 1):
            decision = forced_decision or self.decide(story, user_message, step, run, tool_registry.list_specs())
            forced_decision = None
            decision.step = step
            if decision.selected_tool == "ask_user":
                run.status = "needs_user_input"
                run.final_summary = decision.user_message or decision.reasoning_summary or "Director needs more user input."
                run.updated_at = utc_now()
                break
            observation = ""
            try:
                result = tool_registry.execute(decision.selected_tool, decision.tool_args, run_id=run.id)
                observation = str(result.get("observation") or result)
                success = bool(result.get("success", True))
                error_type = str(result.get("error_type") or "")
                error_message = str(result.get("error_message") or "")
                trace_step = AgentTraceStep(
                    step=step,
                    run_id=run.id,
                    story_id=story_id,
                    chapter_index=self._chapter_from_args(decision.tool_args),
                    stage="director_execute",
                    action=decision.selected_tool,
                    selected_tool=decision.selected_tool,
                    reasoning_summary=decision.reasoning_summary,
                    tool_args=decision.tool_args,
                    input_summary=decision.reflection or decision.reasoning_summary,
                    output_summary=str(result.get("output_summary") or observation),
                    observation=observation,
                    memory_hits_count=int((result.get("trace_event") or {}).get("memory_hits_count", 0) or 0),
                    review_score_after=result.get("review_score_after"),
                    success=success,
                    error_type=error_type,
                    error_message=error_message,
                    duration_ms=int(result.get("duration_ms", 0) or 0),
                    error=error_message,
                )
                trace_event = result.get("trace_event")
                if isinstance(trace_event, dict):
                    run.trace_events.append(AgentTraceEvent.model_validate(trace_event).model_dump())
            except Exception as exc:
                error_type = classify_exception(exc)
                trace_step = AgentTraceStep(
                    step=step,
                    run_id=run.id,
                    story_id=story_id,
                    chapter_index=self._chapter_from_args(decision.tool_args),
                    stage="director_execute",
                    action=decision.selected_tool,
                    selected_tool=decision.selected_tool,
                    reasoning_summary=decision.reasoning_summary,
                    tool_args=decision.tool_args,
                    observation="",
                    success=False,
                    error_type=error_type,
                    error_message=str(exc),
                    error=str(exc),
                )
                run.trace_events.append(
                    AgentTraceEvent(
                        run_id=run.id,
                        story_id=story_id,
                        chapter_index=self._chapter_from_args(decision.tool_args),
                        stage="director_execute",
                        action=decision.selected_tool,
                        selected_tool=decision.selected_tool,
                        tool_args=decision.tool_args,
                        input_summary=decision.reasoning_summary,
                        success=False,
                        error_type=error_type,
                        error_message=str(exc),
                    ).model_dump()
                )
                error_message = str(exc)
                success = False
            run.steps.append(trace_step)
            run.updated_at = utc_now()
            if not success:
                if is_recoverable(error_type) and recovery_attempts < 2:
                    recovery_attempts += 1
                    forced_decision = self._recovery_decision(story, decision, error_type, error_message, step + 1)
                    run.trace_events.append(
                        AgentTraceEvent(
                            run_id=run.id,
                            story_id=story_id,
                            chapter_index=self._chapter_from_args(forced_decision.tool_args),
                            stage="reflect_replan",
                            action=forced_decision.selected_tool,
                            selected_tool=forced_decision.selected_tool,
                            tool_args=forced_decision.tool_args,
                            input_summary=observation or error_message,
                            observation=forced_decision.reflection,
                            success=True,
                        ).model_dump()
                    )
                    continue
                run.status = "failed"
                run.final_summary = f"Director stopped after unrecoverable tool failure: {error_type} {error_message}"
                break
            if not decision.should_continue:
                run.status = "completed"
                run.final_summary = observation
                break
        else:
            run.status = "max_steps_reached"
            run.final_summary = f"Stopped after {max_steps} steps."

        if not run.final_summary and run.steps:
            run.final_summary = run.steps[-1].observation or run.steps[-1].error
        if run.status == "running":
            run.status = "completed"
        run.updated_at = utc_now()
        return run

    def _chapter_from_args(self, args: dict) -> int | None:
        """从工具参数中提取章节索引，非整数时返回 None。"""
        value = args.get("chapter_index")
        return value if isinstance(value, int) else None

    def _recovery_decision(
        self,
        story: Story,
        failed: AgentDecision,
        error_type: str,
        error_message: str,
        step: int,
    ) -> AgentDecision:
        """根据错误类型生成恢复决策：修复参数、补齐前置条件、重试或降级。"""
        chapter = self._safe_chapter(failed.tool_args, story)
        if error_type == ERROR_TOOL_ARG_INVALID:
            fixed_args = dict(failed.tool_args)
            fixed_args["chapter_index"] = chapter
            return AgentDecision(
                step=step,
                intent="repair_tool_args",
                selected_tool=failed.selected_tool,
                reasoning_summary="Repair invalid tool arguments and retry once.",
                tool_args=fixed_args,
                should_continue=failed.should_continue,
                fallback_action=failed.fallback_action,
                reflection=f"Recovered from tool_arg_invalid: {error_message}",
                retry_count=failed.retry_count + 1,
            )
        if error_type == ERROR_PRECONDITION_MISSING:
            if len(story.outlines) < chapter:
                return AgentDecision(
                    step=step,
                    intent="repair_missing_outline",
                    selected_tool="create_outline",
                    reasoning_summary="A required outline is missing, so create outline coverage first.",
                    tool_args={"num_chapters": chapter},
                    should_continue=True,
                    fallback_action=failed.selected_tool,
                    reflection=f"Recovered from missing precondition before {failed.selected_tool}: {error_message}",
                )
            chapter_state = story.chapters.get(chapter)
            if chapter_state is None or not chapter_state.beats:
                return AgentDecision(
                    step=step,
                    intent="repair_missing_beats",
                    selected_tool="create_beats",
                    reasoning_summary="Scene beats are missing, so create beats before retrying writing.",
                    tool_args={"chapter_index": chapter},
                    should_continue=True,
                    fallback_action=failed.selected_tool,
                    reflection=f"Recovered from missing beats before {failed.selected_tool}: {error_message}",
                )
        if error_type == ERROR_QUALITY_GATE_FAILED:
            return AgentDecision(
                step=step,
                intent="repair_quality_gate",
                selected_tool="auto_write_chapter",
                reasoning_summary="Quality gate failed, so route the chapter through auto revision.",
                tool_args={"chapter_index": chapter},
                should_continue=False,
                reflection=f"Recovered from quality gate failure: {error_message}",
            )
        return AgentDecision(
            step=step,
            intent="retry_tool",
            selected_tool=failed.selected_tool,
            reasoning_summary="Retry a recoverable tool execution failure once.",
            tool_args={"chapter_index": chapter} if "chapter_index" in failed.tool_args else dict(failed.tool_args),
            should_continue=failed.should_continue,
            reflection=f"Retrying after {error_type}: {error_message}",
            retry_count=failed.retry_count + 1,
        )

    def _safe_chapter(self, args: dict, story: Story) -> int:
        """安全获取章节索引，默认返回当前章节（最小为 1）。"""
        value = args.get("chapter_index")
        if value is None or not isinstance(value, (int, float)):
            return max(story.current_chapter, 1)
        return max(1, int(value))

    def decide(
        self,
        story: Story,
        user_message: str,
        step: int,
        run: AgentTraceRun,
        tools: list[dict],
    ) -> AgentDecision:
        """调用 LLM 选择下一步工具，失败时回退到规则决策。"""
        system = (
            "You are NovelDirectorAgent, a tool-using supervisor for a long-form fiction project. "
            "Choose exactly one next tool based on the user's natural-language request and current story state. "
            "If the request is ambiguous and cannot be safely acted on, choose selected_tool='ask_user'. "
            "Output strict JSON matching AgentDecision."
        )
        state = {
            "story_id": str(story.id),
            "title": story.title,
            "premise": story.premise,
            "status": story.status,
            "current_chapter": story.current_chapter,
            "outline_count": len(story.outlines),
            "chapter_count": len(story.chapters),
            "chapters": [
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "status": chapter.status,
                    "has_content": bool(chapter.content),
                }
                for chapter in sorted(story.chapters.values(), key=lambda item: item.index)[-12:]
            ],
            "pending_foreshadowings": [
                item.model_dump() for item in story.foreshadowings if item.status == "pending"
            ][:12],
            "memory_cards": len(story.memory_cards),
            "last_observations": [
                {
                    "step": item.step,
                    "tool": item.selected_tool,
                    "success": item.success,
                    "observation": item.observation,
                    "error": item.error,
                }
                for item in run.steps[-6:]
            ],
        }
        payload = {
            "marker": "director_decision",
            "step": step,
            "user_message": user_message,
            "story_state": state,
            "tools": tools,
            "output_schema": {
                "step": "int",
                "intent": "short intent classification",
                "selected_tool": "one tool name or ask_user",
                "reasoning_summary": "brief, user-safe reason",
                "tool_args": "object",
                "should_continue": "bool",
                "user_message": "question to user if selected_tool is ask_user, otherwise empty",
            },
        }
        try:
            raw = self._chat(system, json.dumps(payload, ensure_ascii=False))
            decision = self._parse_model(raw, AgentDecision)
        except Exception:
            decision = self._fallback_decision(story, user_message, step)
        if decision.step != step:
            decision.step = step
        if decision.selected_tool != "ask_user" and not any(tool["name"] == decision.selected_tool for tool in tools):
            decision = self._fallback_decision(story, user_message, step)
        return decision

    def _fallback_decision(self, story: Story, user_message: str, step: int) -> AgentDecision:
        """基于关键词匹配的规则回退决策，不依赖 LLM。"""
        text = user_message.lower()
        chapter = self._extract_chapter(text) or max(story.current_chapter, 1)
        if "伏笔" in user_message or "foreshadow" in text:
            return AgentDecision(step=step, intent="inspect_foreshadowing", selected_tool="list_foreshadowings", reasoning_summary="The user asked about unresolved foreshadowing.", tool_args={"status": "pending"}, should_continue=False)
        if "检查" in user_message or "审查" in user_message or "review" in text:
            return AgentDecision(step=step, intent="review_chapter", selected_tool="review_chapter", reasoning_summary="The user asked to inspect a chapter.", tool_args={"chapter_index": chapter}, should_continue=False)
        if "改" in user_message or "修" in user_message or "revise" in text:
            return AgentDecision(step=step, intent="revise_chapter", selected_tool="revise_chapter", reasoning_summary="The user asked to revise an existing chapter.", tool_args={"chapter_index": chapter}, should_continue=False)
        if "继续" in user_message or "下一章" in user_message or "write" in text:
            next_chapter = max(story.current_chapter + 1, 1)
            if len(story.outlines) < next_chapter:
                return AgentDecision(step=step, intent="create_outline", selected_tool="create_outline", reasoning_summary="The next chapter needs outline coverage first.", tool_args={"num_chapters": next_chapter}, should_continue=True)
            return AgentDecision(step=step, intent="write_next_chapter", selected_tool="auto_write_chapter", reasoning_summary="The user asked to continue writing the next chapter.", tool_args={"chapter_index": next_chapter}, should_continue=False)
        return AgentDecision(step=step, intent="show_status", selected_tool="show_status", reasoning_summary="Default to showing status when intent is unclear.", tool_args={}, should_continue=False)

    def _extract_chapter(self, text: str) -> int | None:
        """从用户消息文本中提取章节号。"""
        import re

        match = re.search(r"(?:第)?\s*(\d+)\s*(?:章|chapter|ch)?", text, re.IGNORECASE)
        return int(match.group(1)) if match else None
