"""Supervisor agent that turns a writing objective into an executable plan."""

from __future__ import annotations

from uuid import uuid4

from novelforge.agents.base import BaseAgent
from novelforge.core.models import AgentTask, AutonomousRunReport, Story


class SupervisorAgent(BaseAgent):
    name = "supervisor"

    def plan_writing_run(
        self,
        story: Story,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
    ) -> AutonomousRunReport:
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
            tasks=tasks,
            summary=f"Planned {len(tasks)} tasks for chapters {start_chapter}-{end_chapter}.",
        )
