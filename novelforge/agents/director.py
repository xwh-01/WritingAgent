"""LLM director agent that chooses tools from live story state."""

from __future__ import annotations

import json
from uuid import uuid4

from novelforge.agents.base import BaseAgent
from novelforge.core.models import AgentDecision, AgentTraceRun, AgentTraceStep, Story, utc_now


class NovelDirectorAgent(BaseAgent):
    name = "director"

    def run(
        self,
        story_id: str,
        user_message: str,
        max_steps: int,
        story: Story,
        tool_registry,
    ) -> AgentTraceRun:
        run = AgentTraceRun(id=f"trace-{uuid4().hex[:10]}", story_id=story_id, user_message=user_message)
        for step in range(1, max(1, max_steps) + 1):
            decision = self.decide(story, user_message, step, run, tool_registry.list_specs())
            if decision.selected_tool == "ask_user":
                run.status = "needs_user_input"
                run.final_summary = decision.user_message or decision.reasoning_summary or "Director needs more user input."
                run.updated_at = utc_now()
                break
            try:
                result = tool_registry.execute(decision.selected_tool, decision.tool_args)
                observation = str(result.get("observation") or result)
                trace_step = AgentTraceStep(
                    step=step,
                    selected_tool=decision.selected_tool,
                    reasoning_summary=decision.reasoning_summary,
                    tool_args=decision.tool_args,
                    observation=observation,
                    success=True,
                )
            except Exception as exc:
                trace_step = AgentTraceStep(
                    step=step,
                    selected_tool=decision.selected_tool,
                    reasoning_summary=decision.reasoning_summary,
                    tool_args=decision.tool_args,
                    observation="",
                    success=False,
                    error=str(exc),
                )
                run.status = "failed"
                run.final_summary = f"Director stopped after tool failure: {exc}"
                run.steps.append(trace_step)
                run.updated_at = utc_now()
                break
            run.steps.append(trace_step)
            run.updated_at = utc_now()
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

    def decide(
        self,
        story: Story,
        user_message: str,
        step: int,
        run: AgentTraceRun,
        tools: list[dict],
    ) -> AgentDecision:
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
        import re

        match = re.search(r"(?:第)?\s*(\d+)\s*(?:章|chapter|ch)?", text, re.IGNORECASE)
        return int(match.group(1)) if match else None
