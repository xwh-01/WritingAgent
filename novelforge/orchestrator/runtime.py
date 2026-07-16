"""Bounded Plan-Act-Observe runtime for story goals."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from novelforge.agents.story_orchestrator import AgentPlan, AgentTask, StoryOrchestratorAgent
from novelforge.domain import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    CandidateStatus,
    ProposalStatus,
    utc_now,
)
from novelforge.orchestrator.tools import StoryAgentToolbox
from novelforge.storage.agent_runs import AgentRunRepository


class StoryAgentRuntime:
    """Execute goals with autonomy bounded by typed tools and step budgets."""

    def __init__(
        self,
        director: StoryOrchestratorAgent,
        toolbox: StoryAgentToolbox,
        repository: AgentRunRepository,
    ) -> None:
        self.director = director
        self.toolbox = toolbox
        self.repository = repository

    def start(self, goal: str, max_steps: int = 12) -> AgentRun:
        story = self.toolbox.engine.current_story
        run = AgentRun(
            story_id=story.id,
            goal=goal.strip(),
            status=AgentRunStatus.RUNNING,
            max_steps=max_steps,
            story_revision=story.revision,
            provider=self.toolbox.engine.config.llm.provider,
            model=self.toolbox.engine.config.llm.model,
        )
        if not run.goal:
            raise ValueError("Agent goal cannot be empty.")
        self.repository.save_run(run)
        try:
            plan = self.director.plan(run.goal, story, self.toolbox.catalog())
            run.plan = [task.model_dump(mode="json") for task in plan.tasks]
            run.updated_at = utc_now()
            self.repository.save_run(run)
            return self._execute(run, plan.tasks)
        except Exception as exc:
            return self._fail_run(run, str(exc))

    def resume(self, run_id: str, user_input: str = "") -> AgentRun:
        run = self.repository.load_run(run_id)
        if run.status is not AgentRunStatus.WAITING_APPROVAL:
            return run
        steps = self.repository.list_steps(run.id)
        if not steps:
            return self._fail_run(run, "Waiting run has no recorded step.")
        last = steps[-1]
        tool_result = last.output_payload.get("tool_result") or {}
        proposal_id = str((tool_result.get("data") or {}).get("proposal_id") or "")
        if proposal_id:
            proposal = self.toolbox.engine.get_revision_proposal(proposal_id)
            if proposal is None:
                return self._fail_run(run, f"Revision proposal {proposal_id} no longer exists.")
            if proposal.status is ProposalStatus.AWAITING_APPROVAL:
                return run
            candidate_id = str(tool_result.get("candidate_id") or "")
            if candidate_id:
                candidate = self.repository.load_candidate(candidate_id)
                candidate.status = (
                    CandidateStatus.COMMITTED
                    if proposal.status is ProposalStatus.ACCEPTED
                    else CandidateStatus.REJECTED
                )
                candidate.updated_at = utc_now()
                self.repository.save_candidate(candidate)
            if proposal.status is ProposalStatus.REJECTED:
                return self._fail_run(run, f"Revision proposal {proposal_id} was rejected.")
        elif not user_input.strip():
            return run
        else:
            plan = self.director.plan(
                f"{run.goal}\n用户补充：{user_input.strip()}",
                self.toolbox.engine.current_story,
                self.toolbox.catalog(),
            )
            run.plan = [task.model_dump(mode="json") for task in plan.tasks]
            run.current_step = 0

        run.status = AgentRunStatus.RUNNING
        run.updated_at = utc_now()
        self.repository.save_run(run)
        tasks = [AgentTask.model_validate(item) for item in run.plan]
        return self._execute(run, tasks, start_index=run.current_step)

    def get(self, run_id: str) -> AgentRun:
        return self.repository.load_run(run_id)

    def details(self, run_id: str) -> dict[str, Any]:
        run = self.repository.load_run(run_id)
        candidates = self.repository.list_candidates(run.id)
        return {
            "run": run.model_dump(mode="json"),
            "steps": [item.model_dump(mode="json") for item in self.repository.list_steps(run.id)],
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "evaluations": {
                str(candidate.id): [
                    item.model_dump(mode="json")
                    for item in self.repository.list_evaluations(candidate.id)
                ]
                for candidate in candidates
            },
        }

    def _execute(
        self,
        run: AgentRun,
        tasks: list[AgentTask],
        start_index: int = 0,
    ) -> AgentRun:
        completed_ids = {
            AgentTask.model_validate(run.plan[index]).id
            for index in range(min(start_index, len(run.plan)))
        }
        observations: list[str] = []
        replans = 0
        cursor = start_index
        while cursor < len(tasks):
            if run.current_step >= run.max_steps:
                return self._fail_run(run, "Agent step budget exhausted.")
            task = tasks[cursor]
            missing = [item for item in task.dependencies if item not in completed_ids]
            if missing:
                return self._fail_run(
                    run,
                    f"Task {task.id} has incomplete dependencies: {', '.join(missing)}",
                )
            step = AgentStep(
                run_id=run.id,
                sequence=len(self.repository.list_steps(run.id)) + 1,
                agent_name=self.director.name,
                action=task.description,
                tool_name=task.selected_tool,
                input_payload={
                    "task": task.model_dump(mode="json"),
                    "story_revision": self.toolbox.engine.current_story.revision,
                },
                decision_summary=f"选择 {task.selected_tool} 完成：{task.description}",
            )
            self.repository.save_step(step)
            started = perf_counter()
            try:
                result = self.toolbox.execute(task.selected_tool, task.tool_args, run)
                evaluation = self.director.evaluate(task, result.model_dump(mode="json"))
                if result.error:
                    evaluation.passed = False
                    evaluation.recommended_action = "replan"
                    evaluation.feedback = result.error
                step.output_payload = {
                    "tool_result": result.model_dump(mode="json"),
                    "evaluation": evaluation.model_dump(mode="json"),
                }
                step.status = AgentStepStatus.COMPLETED
                step.duration_ms = round((perf_counter() - started) * 1000)
                step.completed_at = utc_now()
                self.repository.save_step(step)
            except Exception as exc:
                step.status = AgentStepStatus.FAILED
                step.duration_ms = round((perf_counter() - started) * 1000)
                step.error = str(exc)
                step.completed_at = utc_now()
                self.repository.save_step(step)
                return self._fail_run(run, str(exc))

            run.current_step += 1
            run.story_revision = self.toolbox.engine.current_story.revision
            run.updated_at = utc_now()
            observations.append(result.observation)
            self.repository.save_run(run)

            if result.requires_approval or evaluation.recommended_action == "await_approval":
                run.status = AgentRunStatus.WAITING_APPROVAL
                run.result_summary = result.observation
                run.updated_at = utc_now()
                return self.repository.save_run(run)

            if not evaluation.passed:
                if evaluation.recoverable and replans < 1:
                    replans += 1
                    failure_context = (
                        f"任务 {task.description} 失败。工具观察：{result.observation}；"
                        f"验收反馈：{evaluation.feedback}"
                    )
                    new_plan: AgentPlan = self.director.plan(
                        run.goal,
                        self.toolbox.engine.current_story,
                        self.toolbox.catalog(),
                        failure_context,
                    )
                    tasks = new_plan.tasks
                    run.plan = [item.model_dump(mode="json") for item in tasks]
                    completed_ids.clear()
                    cursor = 0
                    run.updated_at = utc_now()
                    self.repository.save_run(run)
                    continue
                return self._fail_run(run, evaluation.feedback or result.error or "Task failed.")

            completed_ids.add(task.id)
            cursor += 1

        run.status = AgentRunStatus.COMPLETED
        run.result_summary = "\n".join(item for item in observations if item)
        run.completed_at = utc_now()
        run.updated_at = run.completed_at
        run.story_revision = self.toolbox.engine.current_story.revision
        return self.repository.save_run(run)

    def _fail_run(self, run: AgentRun, error: str) -> AgentRun:
        run.status = AgentRunStatus.FAILED
        run.error = error
        run.completed_at = utc_now()
        run.updated_at = run.completed_at
        return self.repository.save_run(run)


__all__ = ["StoryAgentRuntime"]
