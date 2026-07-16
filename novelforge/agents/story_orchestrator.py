"""Goal-driven orchestrator that delegates work through typed tools."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import Field

from novelforge.agents.base import BaseAgent
from novelforge.domain import DomainModel, Story


class AgentTask(DomainModel):
    id: str
    description: str
    selected_tool: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class AgentPlan(DomainModel):
    objective: str
    success_criteria: list[str] = Field(default_factory=list)
    tasks: list[AgentTask] = Field(default_factory=list)
    status: str = "planned"
    assumptions: list[str] = Field(default_factory=list)


class CriterionResult(DomainModel):
    criterion: str
    passed: bool
    evidence: str = ""


class TaskEvaluation(DomainModel):
    passed: bool
    criterion_results: list[CriterionResult] = Field(default_factory=list)
    recoverable: bool = False
    recommended_action: Literal["complete", "retry", "replan", "await_approval", "abort"] = (
        "complete"
    )
    feedback: str = ""


class StoryOrchestratorAgent(BaseAgent):
    """Translate a user goal into bounded tasks and evaluate observations."""

    name = "story_orchestrator"

    def plan(
        self,
        objective: str,
        story: Story,
        tool_catalog: list[dict[str, Any]],
        failure_context: str = "",
    ) -> AgentPlan:
        system = (
            "你是长篇小说项目的 Story Orchestrator。把用户目标拆成最少且可验证的任务，"
            "只能使用工具目录中的工具。你负责规划和选择工具，不能直接声称已经修改故事。"
            "不得绕过质量门禁，不得把候选稿当作正式事实。严格输出 AgentPlan JSON。"
        )
        payload = {
            "marker": "director_plan",
            "objective": objective,
            "failure_context": failure_context,
            "story_state": {
                "story_id": str(story.id),
                "revision": story.revision,
                "status": story.status,
                "current_chapter": story.current_chapter,
                "outline_count": len(story.design.outlines),
                "characters": [item.name for item in story.design.characters.values()],
            },
            "tools": tool_catalog,
        }
        try:
            plan = self._parse_model(
                self._chat(system, json.dumps(payload, ensure_ascii=False, default=str)),
                AgentPlan,
            )
            self._validate_tools(plan, tool_catalog)
            if not plan.tasks:
                raise ValueError("Orchestrator returned an empty plan.")
            return plan
        except Exception:
            return self._fallback_plan(objective, story)

    def evaluate(self, task: AgentTask, tool_result: dict[str, Any]) -> TaskEvaluation:
        system = (
            "你是任务验收 Agent。只根据结构化工具结果检查成功标准。"
            "不得根据主观愿望宣称成功。严格输出 TaskEvaluation JSON。"
        )
        payload = {
            "marker": "director_task_evaluation",
            "task": task.model_dump(),
            "tool_result": tool_result,
        }
        try:
            return self._parse_model(
                self._chat(system, json.dumps(payload, ensure_ascii=False, default=str)),
                TaskEvaluation,
            )
        except Exception:
            observation = str(tool_result.get("observation") or "")
            requires_approval = bool(tool_result.get("requires_approval"))
            passed = bool(observation) and not tool_result.get("error")
            return TaskEvaluation(
                passed=passed,
                criterion_results=[
                    CriterionResult(criterion=item, passed=passed, evidence=observation[:300])
                    for item in task.success_criteria
                ],
                recoverable=not passed,
                recommended_action=(
                    "await_approval" if requires_approval else ("complete" if passed else "replan")
                ),
                feedback="" if passed else str(tool_result.get("error") or "工具执行失败"),
            )

    @staticmethod
    def _validate_tools(plan: AgentPlan, catalog: list[dict[str, Any]]) -> None:
        available = {str(item["name"]) for item in catalog}
        unknown = [task.selected_tool for task in plan.tasks if task.selected_tool not in available]
        if unknown:
            raise ValueError("Unknown tools: " + ", ".join(unknown))
        seen: set[str] = set()
        for task in plan.tasks:
            if task.id in seen:
                raise ValueError(f"Duplicate task id: {task.id}")
            missing = [dependency for dependency in task.dependencies if dependency not in seen]
            if missing:
                raise ValueError(
                    f"Task {task.id} depends on unavailable earlier tasks: {', '.join(missing)}"
                )
            seen.add(task.id)

    @staticmethod
    def _fallback_plan(objective: str, story: Story) -> AgentPlan:
        lowered = objective.lower()
        match = re.search(r"第?\s*(\d+)\s*章", objective)
        chapter = int(match.group(1)) if match else max(story.current_chapter + 1, 1)
        if any(token in lowered for token in ("写", "继续", "下一章", "write")):
            tasks = [
                AgentTask(
                    id="ensure-outline",
                    description=f"确保大纲覆盖第{chapter}章",
                    selected_tool="create_outline",
                    tool_args={"num_chapters": chapter},
                    success_criteria=[f"存在第{chapter}章大纲"],
                ),
                AgentTask(
                    id="write-chapter",
                    description=f"生成并验收第{chapter}章",
                    selected_tool="auto_write_chapter",
                    tool_args={"chapter_index": chapter},
                    dependencies=["ensure-outline"],
                    success_criteria=["候选稿通过质量门禁", "正式正文和知识已提交"],
                ),
            ]
        elif any(token in lowered for token in ("改", "修", "revise")):
            tasks = [
                AgentTask(
                    id="revise-chapter",
                    description=f"为第{chapter}章生成审批式修订提案",
                    selected_tool="revise_chapter",
                    tool_args={"chapter_index": chapter, "revision_instruction": objective},
                    success_criteria=["生成未覆盖正式正文的修订提案"],
                )
            ]
        elif any(token in lowered for token in ("检查", "审查", "review")):
            tasks = [
                AgentTask(
                    id="review-chapter",
                    description=f"审查第{chapter}章",
                    selected_tool="review_chapter",
                    tool_args={"chapter_index": chapter},
                    success_criteria=["返回结构化评审结果"],
                )
            ]
        else:
            tasks = [
                AgentTask(
                    id="show-status",
                    description="读取当前故事状态",
                    selected_tool="show_status",
                    success_criteria=["返回当前故事状态"],
                )
            ]
        return AgentPlan(
            objective=objective,
            success_criteria=["完成用户目标", "不绕过正式事实与质量边界"],
            tasks=tasks,
        )


__all__ = [
    "AgentPlan",
    "AgentTask",
    "CriterionResult",
    "StoryOrchestratorAgent",
    "TaskEvaluation",
]
