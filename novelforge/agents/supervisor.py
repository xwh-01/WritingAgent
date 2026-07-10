"""Supervisor agent that turns a writing objective into an executable plan."""

from __future__ import annotations

import json
from uuid import uuid4

from novelforge.agents.base import BaseAgent
from novelforge.core.models import AgentTask, AutonomousRunReport, Story


class SupervisorAgent(BaseAgent):
    """监管 Agent，将写作目标转化为可执行的任务计划。"""

    name = "supervisor"
    allowed_actions = {
        "ensure_outline",
        "generate_beats",
        "write_chapter",
        "auto_write_chapter",
        "audit_chapter_continuity",
        "memory_checkpoint",
    }

    def plan_writing_run(
        self,
        story: Story,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
    ) -> AutonomousRunReport:
        """规划写作运行：优先用 LLM 生成任务计划，失败则用规则生成。"""
        llm_plan = self._plan_with_llm(story, objective, start_chapter, end_chapter, use_auto_revision)
        if llm_plan is not None:
            return llm_plan
        return self._rule_plan(story, objective, start_chapter, end_chapter, use_auto_revision)

    def _plan_with_llm(
        self,
        story: Story,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> AutonomousRunReport | None:
        """调用 LLM 生成任务计划并校验，失败返回 None 以触发规则回退。"""
        system = (
            "You are the SupervisorAgent for a long-form fiction writing system. "
            "Plan an executable tool sequence for a multi-agent novel writing run. "
            "Output strict JSON only."
        )
        user = {
            "marker": "supervisor_plan",
            "objective": objective,
            "story": {
                "title": story.title,
                "premise": story.premise,
                "genre": story.genre,
                "style_guide": story.style_guide,
                "outline_count": len(story.outlines),
                "chapter_count": len(story.chapters),
                "memory_cards": len(story.memory_cards),
                "open_foreshadowings": [
                    item.description for item in story.foreshadowings if item.status == "pending"
                ][:8],
            },
            "chapter_range": {"start": start_chapter, "end": end_chapter},
            "use_auto_revision": use_auto_revision,
            "available_actions": sorted(self.allowed_actions),
            "required_constraints": [
                "ensure_outline must appear before chapter-level tasks if outlines may be missing",
                "each chapter should normally include beats, writing or auto revision, continuity audit, and memory checkpoint",
                "chapter_index must be within the requested chapter_range except ensure_outline",
                "write_chapter and auto_write_chapter are alternatives for a chapter",
            ],
            "output_schema": {
                "strategy": "short string",
                "notes": "short explanation",
                "tasks": [
                    {
                        "agent": "agent name",
                        "action": "one available action",
                        "reason": "why this action is useful",
                        "chapter_index": "integer or null",
                        "input_summary": "short task input",
                    }
                ],
            },
        }
        try:
            raw = self._chat(system, json.dumps(user, ensure_ascii=False))
            data = self._extract_json(raw)
            tasks = self._validate_llm_tasks(data, objective, start_chapter, end_chapter, use_auto_revision)
        except Exception:
            return None
        if not tasks:
            return None
        strategy = str(data.get("strategy") or "llm")
        notes = str(data.get("notes") or "Supervisor planned with LLM and validated the executable tasks.")
        return AutonomousRunReport(
            id=f"run-{uuid4().hex[:10]}",
            objective=objective,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            use_auto_revision=use_auto_revision,
            planning_strategy=strategy,
            planning_notes=notes,
            tasks=tasks,
            summary=f"LLM Supervisor planned {len(tasks)} tasks for chapters {start_chapter}-{end_chapter}.",
        )

    def _validate_llm_tasks(
        self,
        data: object,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> list[AgentTask]:
        """校验 LLM 返回的任务列表：过滤非法动作、去重，再补全最低保障计划。"""
        if not isinstance(data, dict):
            return []
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list):
            return []
        tasks: list[AgentTask] = []
        seen_chapter_actions: set[tuple[int, str]] = set()
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if action not in self.allowed_actions:
                continue
            chapter_index = item.get("chapter_index")
            if action == "ensure_outline":
                chapter_index = None
            elif not isinstance(chapter_index, int) or not (start_chapter <= chapter_index <= end_chapter):
                continue
            if action == "write_chapter" and use_auto_revision:
                action = "auto_write_chapter"
            if action == "auto_write_chapter" and not use_auto_revision:
                action = "write_chapter"
            if isinstance(chapter_index, int):
                key = (chapter_index, action)
                if key in seen_chapter_actions:
                    continue
                seen_chapter_actions.add(key)
            tasks.append(
                AgentTask(
                    id=f"task-{uuid4().hex[:8]}",
                    step_index=len(tasks) + 1,
                    agent=str(item.get("agent") or self._agent_for_action(action)),
                    action=action,
                    reason=str(item.get("reason") or "Selected by SupervisorAgent."),
                    chapter_index=chapter_index,
                    input_summary=str(item.get("input_summary") or objective),
                    metadata={"planned_by": "llm"},
                )
            )
        return self._complete_minimum_plan(tasks, objective, start_chapter, end_chapter, use_auto_revision)

    def _rule_plan(
        self,
        story: Story,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
    ) -> AutonomousRunReport:
        """基于规则的确定性任务计划：按章节顺序生成大纲 → 节拍 → 写作 → 审计 → 记忆检查点。"""
        tasks: list[AgentTask] = []

        def add(
            agent: str,
            action: str,
            reason: str,
            chapter_index: int | None = None,
            input_summary: str = "",
        ) -> None:
            tasks.append(
                AgentTask(
                    id=f"task-{uuid4().hex[:8]}",
                    step_index=len(tasks) + 1,
                    agent=agent,
                    action=action,
                    reason=reason,
                    chapter_index=chapter_index,
                    input_summary=input_summary,
                )
            )

        add(
            "PlannerAgent",
            "ensure_outline",
            "The run needs a chapter-level map before drafting can continue.",
            input_summary=f"Need outlines through chapter {end_chapter}.",
        )
        for chapter_index in range(start_chapter, end_chapter + 1):
            add(
                "PlannerAgent",
                "generate_beats",
                "Scene beats give the writer concrete goals, resistance, turns, and outcomes.",
                chapter_index=chapter_index,
            )
            if use_auto_revision:
                add(
                    "WriterAgent+CriticAgent+EditorAgent",
                    "auto_write_chapter",
                    "Draft, review, revise, and re-review until the configured quality gate is reached.",
                    chapter_index=chapter_index,
                    input_summary=objective,
                )
            else:
                add(
                    "WriterAgent",
                    "write_chapter",
                    "Create a publishable draft using the story context and long-form memory.",
                    chapter_index=chapter_index,
                    input_summary=objective,
                )
            add(
                "ContinuityAuditorAgent",
                "audit_chapter_continuity",
                "Check long-form continuity, character state, causality, and open threads.",
                chapter_index=chapter_index,
            )
            add(
                "MemoryEngine",
                "memory_checkpoint",
                "Confirm the chapter has updated searchable memory for future retrieval.",
                chapter_index=chapter_index,
            )

        return AutonomousRunReport(
            id=f"run-{uuid4().hex[:10]}",
            objective=objective,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            use_auto_revision=use_auto_revision,
            planning_strategy="rule",
            planning_notes="LLM planning was unavailable or invalid, so SupervisorAgent used the deterministic fallback.",
            tasks=tasks,
            summary=f"Planned {len(tasks)} tasks for chapters {start_chapter}-{end_chapter}.",
        )

    def _complete_minimum_plan(
        self,
        tasks: list[AgentTask],
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> list[AgentTask]:
        """确保任务计划包含每个章节的最低必要步骤（大纲、节拍、写作、审计、记忆）。"""
        if not any(task.action == "ensure_outline" for task in tasks):
            tasks.insert(
                0,
                AgentTask(
                    id=f"task-{uuid4().hex[:8]}",
                    step_index=1,
                    agent="PlannerAgent",
                    action="ensure_outline",
                    reason="Supervisor added a safety planning step before chapter work.",
                    input_summary=f"Need outlines through chapter {end_chapter}.",
                    metadata={"planned_by": "supervisor_guardrail"},
                ),
            )
        for chapter_index in range(start_chapter, end_chapter + 1):
            actions = {task.action for task in tasks if task.chapter_index == chapter_index}
            required = [
                ("PlannerAgent", "generate_beats", "Prepare concrete scene beats."),
                (
                    "WriterAgent+CriticAgent+EditorAgent" if use_auto_revision else "WriterAgent",
                    "auto_write_chapter" if use_auto_revision else "write_chapter",
                    "Produce chapter content through the selected writing path.",
                ),
                ("ContinuityAuditorAgent", "audit_chapter_continuity", "Check long-form consistency."),
                ("MemoryEngine", "memory_checkpoint", "Persist memory for future chapters."),
            ]
            for agent, action, reason in required:
                if action not in actions:
                    tasks.append(
                        AgentTask(
                            id=f"task-{uuid4().hex[:8]}",
                            step_index=len(tasks) + 1,
                            agent=agent,
                            action=action,
                            reason=reason,
                            chapter_index=chapter_index,
                            input_summary=objective,
                            metadata={"planned_by": "supervisor_guardrail"},
                        )
                    )
        for index, task in enumerate(tasks, 1):
            task.step_index = index
        return tasks

    def _agent_for_action(self, action: str) -> str:
        """将动作名称映射到对应的 Agent 名称。"""
        return {
            "ensure_outline": "PlannerAgent",
            "generate_beats": "PlannerAgent",
            "write_chapter": "WriterAgent",
            "auto_write_chapter": "WriterAgent+CriticAgent+EditorAgent",
            "audit_chapter_continuity": "ContinuityAuditorAgent",
            "memory_checkpoint": "MemoryEngine",
        }.get(action, "SupervisorAgent")
