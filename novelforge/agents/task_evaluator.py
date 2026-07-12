"""Goal-oriented evaluator for Director task results."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import CriterionResult, DirectorTask, TaskEvaluation


class TaskEvaluatorAgent(BaseAgent):
    """依据任务成功标准验收工具结果，而不是把“调用成功”当作完成。"""

    name = "task_evaluator"

    def evaluate(self, objective: str, task: DirectorTask, result: dict) -> TaskEvaluation:
        if not result.get("success", True):
            return TaskEvaluation(
                passed=False,
                recoverable=True,
                recommended_action="retry",
                feedback=str(result.get("error_message") or result.get("observation") or "Tool failed."),
            )
        criteria = task.success_criteria or ["工具产生了与当前任务相关的有效结果"]
        payload = {
            "marker": "director_task_evaluation",
            "objective": objective,
            "task": task.model_dump(exclude={"evaluation"}),
            "tool_result": {
                "observation": result.get("observation", ""),
                "output_summary": result.get("output_summary", ""),
                "requires_approval": bool(result.get("requires_approval")),
                "data": result.get("data"),
            },
            "output_schema": TaskEvaluation.model_json_schema(),
        }
        system = (
            "You evaluate whether a fiction-project task met its explicit success criteria. "
            "Use observable evidence only. A valid revision proposal passes generation but must recommend "
            "await_approval. Output strict TaskEvaluation JSON."
        )
        try:
            evaluation = self._parse_model(
                self._chat(system, json.dumps(payload, ensure_ascii=False)), TaskEvaluation
            )
        except Exception:
            evaluation = TaskEvaluation(
                passed=True,
                criterion_results=[
                    CriterionResult(
                        criterion=criterion,
                        passed=True,
                        evidence=str(result.get("observation") or "Tool completed successfully."),
                    )
                    for criterion in criteria
                ],
                recommended_action="await_approval" if result.get("requires_approval") else "complete",
            )
        if result.get("requires_approval"):
            evaluation.passed = True
            evaluation.recommended_action = "await_approval"
        return evaluation
