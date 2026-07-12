"""LLM director agent that chooses tools from live story state."""

from __future__ import annotations

import json
from uuid import uuid4

from novelforge.agents.base import BaseAgent
from novelforge.core.models import (
    AgentDecision,
    AgentTraceRun,
    AgentTraceStep,
    DirectorPlan,
    DirectorTask,
    Story,
    utc_now,
)
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
        task_evaluator=None,
        existing_run: AgentTraceRun | None = None,
    ) -> AgentTraceRun:
        """执行目标驱动计划，逐项验收，并在失败、追问或审批时持久化暂停。"""
        run = existing_run or AgentTraceRun(
            id=f"trace-{uuid4().hex[:10]}", story_id=story_id, user_message=user_message
        )
        if run.plan is None:
            run.plan = self.create_plan(story, user_message, tool_registry.list_specs())
        run.status = "running"
        run.plan.status = "running"
        run.pending_question = ""
        start_step = len(run.steps) + 1
        for step_number in range(start_step, start_step + max(1, max_steps)):
            task = self._next_ready_task(run.plan)
            if task is None:
                if all(item.status == "completed" for item in run.plan.tasks):
                    run.status = "completed"
                    run.plan.status = "completed"
                    run.final_summary = f"Completed objective: {run.plan.objective}"
                else:
                    run.status = "failed"
                    run.plan.status = "failed"
                    run.final_summary = "Director plan has unresolved task dependencies."
                break
            if task.selected_tool == "ask_user":
                question = task.description or "请补充完成任务所需的信息。"
                run.status = "needs_user_input"
                run.plan.status = "waiting_user"
                run.pending_question = question
                from novelforge.core.models import UserQuestion
                run.pending_user_question = UserQuestion(
                    question=question,
                    reason="Director cannot safely continue without this decision.",
                    required_for_task=task.id,
                )
                run.final_summary = question
                break
            task.status = "running"
            task.attempts += 1
            result = tool_registry.execute(task.selected_tool, task.tool_args, run_id=run.id)
            success = bool(result.get("success", True))
            observation = str(result.get("observation") or result)
            error_message = str(result.get("error_message") or "")
            trace_step = AgentTraceStep(
                step=step_number,
                run_id=run.id,
                story_id=story_id,
                chapter_index=self._chapter_from_args(task.tool_args),
                stage="director_execute",
                action=task.selected_tool,
                selected_tool=task.selected_tool,
                reasoning_summary=task.description,
                tool_args=task.tool_args,
                input_summary="; ".join(task.success_criteria),
                output_summary=str(result.get("output_summary") or observation),
                observation=observation,
                success=success,
                error_type=str(result.get("error_type") or ""),
                error_message=error_message,
                duration_ms=int(result.get("duration_ms", 0) or 0),
                error=error_message,
            )
            run.steps.append(trace_step)
            trace_event = result.get("trace_event")
            if isinstance(trace_event, dict):
                run.trace_events.append(AgentTraceEvent.model_validate(trace_event).model_dump())
            evaluation = (
                task_evaluator.evaluate(run.plan.objective, task, result)
                if task_evaluator is not None
                else None
            )
            task.evaluation = evaluation
            task.observation = observation or error_message
            passed = success and (evaluation is None or evaluation.passed)
            if passed:
                task.status = "completed"
            elif task.attempts < task.max_attempts and (evaluation is None or evaluation.recoverable):
                if evaluation is not None and evaluation.recommended_action == "ask_user":
                    task.status = "pending"
                    run.status = "needs_user_input"
                    run.plan.status = "waiting_user"
                    run.pending_question = evaluation.feedback or "请补充完成当前任务所需的信息。"
                    from novelforge.core.models import UserQuestion
                    run.pending_user_question = UserQuestion(
                        question=run.pending_question,
                        reason="Task evaluator requires a user decision.",
                        required_for_task=task.id,
                    )
                    run.final_summary = run.pending_question
                    break
                task.status = "pending"
                feedback = evaluation.feedback if evaluation else error_message
                task.description = f"Retry with evaluator feedback: {feedback}"
                if task.selected_tool == "revise_chapter" and feedback:
                    previous = str(task.tool_args.get("revision_instruction") or "")
                    task.tool_args["revision_instruction"] = f"{previous}\n验收反馈：{feedback}"
                run.plan.replan_count += 1
            else:
                task.status = "failed"
                if run.plan.replan_count < run.plan.max_replans:
                    run.plan.replan_count += 1
                    recovery = self._recovery_task(story, task, result)
                    if recovery is not None:
                        task.status = "pending"
                        task.attempts = 0
                        task.dependencies.append(recovery.id)
                        run.plan.tasks.append(recovery)
                        continue
                run.status = "failed"
                run.plan.status = "failed"
                run.final_summary = evaluation.feedback if evaluation else error_message or observation
                break
            if task.selected_tool == "analyze_character_continuity":
                self._append_character_repair_tasks(story, run.plan, task, result, user_message)
            if result.get("requires_approval"):
                proposal_id = str((result.get("data") or {}).get("id") or "")
                if proposal_id and proposal_id not in run.proposal_ids:
                    run.proposal_ids.append(proposal_id)
                run.status = "awaiting_approval"
                run.plan.status = "awaiting_approval"
                run.final_summary = observation
                break
            if all(item.status == "completed" for item in run.plan.tasks):
                run.status = "completed"
                run.plan.status = "completed"
                run.final_summary = f"Completed objective: {run.plan.objective}"
                break
        else:
            run.status = "paused"
            run.plan.status = "paused"
            run.final_summary = f"Checkpoint saved after {len(run.steps)} total steps; continue this run to finish."
        run.updated_at = utc_now()
        return run

    def create_plan(self, story: Story, objective: str, tools: list[dict]) -> DirectorPlan:
        """由模型生成完整任务计划；解析失败时使用可复现的领域计划。"""
        payload = {
            "marker": "director_plan",
            "objective": objective,
            "story_state": self._story_state(story),
            "tools": tools,
            "rules": [
                "Use only listed tools or ask_user.",
                "Create explicit success criteria for every task.",
                "Any revision must create a proposal and await approval.",
                "Use dependencies for ordered multi-step work.",
            ],
            "output_schema": DirectorPlan.model_json_schema(),
        }
        try:
            plan = self._parse_model(
                self._chat(
                    "You are a goal-driven director for a long-form fiction project. Plan all required work as structured tasks.",
                    json.dumps(payload, ensure_ascii=False),
                ),
                DirectorPlan,
            )
            valid_tools = {item["name"] for item in tools} | {"ask_user"}
            if not plan.tasks or any(task.selected_tool not in valid_tools for task in plan.tasks):
                raise ValueError("Director returned an empty or invalid plan.")
            return plan
        except Exception:
            return self._fallback_plan(story, objective)

    def _fallback_plan(self, story: Story, objective: str) -> DirectorPlan:
        text = objective.lower()
        chapter = self._extract_chapter(text)
        criteria = ["完成用户明确提出的目标", "保留故事既有事实与连续性"]
        tasks: list[DirectorTask] = []
        if any(token in objective for token in ("人设", "角色一致", "角色连续")) or "character" in text:
            character = self._find_character(story, objective)
            start, end = self._extract_chapter_range(objective, story)
            if not character:
                return DirectorPlan(
                    objective=objective,
                    success_criteria=criteria,
                    tasks=[DirectorTask(description="你想检查哪位角色的人设或状态轨迹？", selected_tool="ask_user")],
                )
            tasks.append(DirectorTask(
                description=(
                    f"审计 {character.name} 在第{start}到第{end}章的人设、知识、情绪、地点和关系轨迹"
                ),
                selected_tool="analyze_character_continuity",
                tool_args={"character": character.id, "start_chapter": start, "end_chapter": end},
                success_criteria=["给出跨章节角色轨迹和带证据的问题", "定位需要修订的章节"],
            ))
            return DirectorPlan(objective=objective, success_criteria=criteria, tasks=tasks)
        if any(token in text for token in ("改", "修", "revise")):
            if chapter is None:
                return DirectorPlan(
                    objective=objective,
                    success_criteria=criteria,
                    tasks=[DirectorTask(description="你想修改第几章？", selected_tool="ask_user")],
                )
            inspect = DirectorTask(
                description=f"读取第{chapter}章当前正文和版本",
                selected_tool="inspect_chapter",
                tool_args={"chapter_index": chapter, "include_content": True},
                success_criteria=["取得当前有效正文和版本"],
            )
            tasks.append(inspect)
            tasks.append(DirectorTask(
                description=f"按用户要求生成第{chapter}章候选修订稿并由 Critic 验收",
                selected_tool="revise_chapter",
                tool_args={"chapter_index": chapter, "revision_instruction": objective},
                dependencies=[inspect.id],
                success_criteria=["候选稿响应用户修改要求", "正式正文尚未被覆盖"],
            ))
        elif "伏笔" in objective or "foreshadow" in text:
            tasks.append(DirectorTask(description="检查未回收伏笔", selected_tool="list_foreshadowings", tool_args={"status": "pending"}, success_criteria=["返回未回收伏笔及状态"]))
        elif any(token in text for token in ("检查", "审查", "review", "连续")):
            if chapter is None:
                return DirectorPlan(objective=objective, success_criteria=criteria, tasks=[DirectorTask(description="你想检查第几章？", selected_tool="ask_user")])
            review = DirectorTask(description=f"审查第{chapter}章", selected_tool="review_chapter", tool_args={"chapter_index": chapter}, success_criteria=["给出带问题分类的审查结果"])
            tasks.append(review)
            if "连续" in objective or "continuity" in text:
                tasks.append(DirectorTask(description=f"检查第{chapter}章长篇连续性", selected_tool="audit_continuity", tool_args={"chapter_index": chapter}, dependencies=[review.id], success_criteria=["给出连续性风险和证据"]))
        elif any(token in text for token in ("继续", "下一章", "write")):
            target = max(story.current_chapter + 1, 1)
            outline = DirectorTask(description=f"确保大纲覆盖第{target}章", selected_tool="create_outline", tool_args={"num_chapters": target}, success_criteria=[f"存在第{target}章大纲"])
            write = DirectorTask(description=f"完成第{target}章写作、审查和修订", selected_tool="auto_write_chapter", tool_args={"chapter_index": target}, dependencies=[outline.id], success_criteria=["章节正文已生成", "质量门执行完成"])
            tasks.extend([outline, write])
        else:
            tasks.append(DirectorTask(description="读取项目状态并确定可执行范围", selected_tool="show_status", success_criteria=["返回当前项目状态"]))
        return DirectorPlan(objective=objective, success_criteria=criteria, tasks=tasks)

    def _append_character_repair_tasks(
        self,
        story: Story,
        plan: DirectorPlan,
        analysis_task: DirectorTask,
        result: dict,
        objective: str,
    ) -> None:
        """将角色轨迹审计发现的漂移点转换为逐章候选修订任务。"""
        report = result.get("data") or {}
        issues = report.get("issues") if isinstance(report, dict) else []
        if not isinstance(issues, list):
            return
        by_chapter: dict[int, list[dict]] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            chapter = issue.get("chapter_index")
            if isinstance(chapter, int) and chapter in story.chapters and story.chapters[chapter].content:
                by_chapter.setdefault(chapter, []).append(issue)
        existing_chapters = {
            int(task.tool_args.get("chapter_index"))
            for task in plan.tasks
            if task.selected_tool == "revise_chapter" and isinstance(task.tool_args.get("chapter_index"), int)
        }
        character_name = str(report.get("character_name") or report.get("character_id") or "该角色")
        for chapter, chapter_issues in sorted(by_chapter.items()):
            if chapter in existing_chapters:
                continue
            evidence = "\n".join(
                f"- {item.get('description', '')}\n  证据: {item.get('evidence', '')}\n  建议: {item.get('suggestion', '')}"
                for item in chapter_issues
            )
            instruction = (
                f"原始任务：{objective}\n"
                f"跨章节角色连续性审计发现 {character_name} 在第{chapter}章存在以下问题：\n{evidence}\n"
                "只补足必要的心理、行动、信息或关系过渡；保留既有关键事件、事实和结尾。"
            )
            plan.tasks.append(DirectorTask(
                description=f"为第{chapter}章生成修复 {character_name} 连续性问题的候选稿",
                selected_tool="revise_chapter",
                tool_args={"chapter_index": chapter, "revision_instruction": instruction},
                dependencies=[analysis_task.id],
                success_criteria=["修订稿修复指定角色连续性证据", "不改变既有关键事件", "等待用户批准后才应用"],
            ))

    def _find_character(self, story: Story, text: str):
        lowered = text.lower()
        matches = [
            character for character in story.characters.values()
            if character.name.lower() in lowered or character.id.lower() in lowered
        ]
        return matches[0] if len(matches) == 1 else None

    def _extract_chapter_range(self, text: str, story: Story) -> tuple[int, int]:
        import re

        match = re.search(r"第?\s*(\d+)\s*(?:到|至|[-~])\s*第?\s*(\d+)\s*章?", text, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            return (start, max(start, end))
        chapter = self._extract_chapter(text)
        if chapter is not None:
            return chapter, chapter
        max_chapter = max(story.chapters.keys(), default=len(story.outlines) or 1)
        return 1, max_chapter

    def _story_state(self, story: Story) -> dict:
        return {
            "story_id": str(story.id), "title": story.title, "status": story.status,
            "current_chapter": story.current_chapter, "outline_count": len(story.outlines),
            "chapters": [{"index": item.index, "status": item.status, "version": item.version, "has_content": bool(item.content)} for item in story.chapters.values()],
            "characters": [item.name for item in story.characters.values()],
            "pending_foreshadowings": [
                {"id": item.id, "description": item.description, "target_chapter": item.target_chapter}
                for item in story.foreshadowings if item.status == "pending"
            ][:12],
            "open_revision_proposals": len([item for item in story.revision_proposals if item.status == "awaiting_approval"]),
        }

    def _next_ready_task(self, plan: DirectorPlan) -> DirectorTask | None:
        completed = {item.id for item in plan.tasks if item.status == "completed"}
        return next((item for item in plan.tasks if item.status == "pending" and all(dep in completed for dep in item.dependencies)), None)

    def _recovery_task(self, story: Story, failed: DirectorTask, result: dict) -> DirectorTask | None:
        chapter = self._safe_chapter(failed.tool_args, story)
        error_type = str(result.get("error_type") or "")
        if error_type == ERROR_PRECONDITION_MISSING:
            if len(story.outlines) < chapter:
                return DirectorTask(description="补齐缺失章节大纲", selected_tool="create_outline", tool_args={"num_chapters": chapter}, success_criteria=["所需大纲存在"])
            return DirectorTask(description="补齐缺失场景节拍", selected_tool="create_beats", tool_args={"chapter_index": chapter}, success_criteria=["章节场景节拍存在"])
        return None

    def _run_legacy(
        self,
        story_id: str,
        user_message: str,
        max_steps: int,
        story: Story,
        tool_registry,
        existing_run: AgentTraceRun | None = None,
    ) -> AgentTraceRun:
        """执行导演运行循环：决策 → 执行 → 观察 → 重试/继续，直到完成或失败。"""
        run = existing_run or AgentTraceRun(
            id=f"trace-{uuid4().hex[:10]}", story_id=story_id, user_message=user_message
        )
        if run.plan is None:
            run.plan = self._create_plan(user_message)
        run.plan.status = "running"
        start_step = len(run.steps) + 1
        recovery_attempts = 0
        forced_decision: AgentDecision | None = None
        for step in range(start_step, start_step + max(1, max_steps)):
            decision = forced_decision or self.decide(story, user_message, step, run, tool_registry.list_specs())
            forced_decision = None
            decision.step = step
            if decision.selected_tool == "ask_user":
                run.status = "needs_user_input"
                question = decision.user_message or decision.reasoning_summary or "Director needs more user input."
                run.pending_question = question
                run.final_summary = question
                run.updated_at = utc_now()
                run.plan.status = "waiting_user"
                break
            task = DirectorTask(
                description=decision.reasoning_summary or decision.intent or decision.selected_tool,
                success_criteria=decision.success_criteria,
                status="running",
                selected_tool=decision.selected_tool,
            )
            run.plan.tasks.append(task)
            observation = ""
            result: dict = {}
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
            task.status = "completed" if success else "failed"
            task.observation = observation or error_message
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
                run.plan.status = "failed"
                run.final_summary = f"Director stopped after unrecoverable tool failure: {error_type} {error_message}"
                break
            if result.get("requires_approval"):
                proposal_id = str((result.get("data") or {}).get("id") or "")
                if proposal_id and proposal_id not in run.proposal_ids:
                    run.proposal_ids.append(proposal_id)
                run.status = "awaiting_approval"
                run.plan.status = "awaiting_approval"
                run.final_summary = observation
                break
            if not decision.should_continue:
                run.status = "completed"
                run.plan.status = "completed"
                run.final_summary = observation
                break
        else:
            run.status = "max_steps_reached"
            run.final_summary = f"Stopped after {len(run.steps)} total steps."

        if not run.final_summary and run.steps:
            run.final_summary = run.steps[-1].observation or run.steps[-1].error
        if run.status == "running":
            run.status = "completed"
            run.plan.status = "completed"
        run.updated_at = utc_now()
        return run

    def _create_plan(self, objective: str) -> DirectorPlan:
        """为一次运行建立可持久化、可在执行中扩展的目标计划。"""
        criteria = ["完成用户明确提出的目标", "保留故事既有事实与连续性"]
        if any(token in objective.lower() for token in ("改", "修", "revise")):
            criteria.extend(["修订稿满足用户的具体要求", "正式正文只在用户批准后更新"])
        return DirectorPlan(objective=objective, success_criteria=criteria)

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
        if decision.selected_tool == "revise_chapter" and not decision.tool_args.get("revision_instruction"):
            decision.tool_args["revision_instruction"] = user_message
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
            return AgentDecision(
                step=step,
                intent="revise_chapter",
                selected_tool="revise_chapter",
                reasoning_summary="The user asked to revise an existing chapter according to their instruction.",
                tool_args={"chapter_index": chapter, "revision_instruction": user_message},
                should_continue=False,
            )
        if "继续" in user_message or "下一章" in user_message or "write" in text:
            next_chapter = max(story.current_chapter + 1, 1)
            if len(story.outlines) < next_chapter:
                return AgentDecision(step=step, intent="create_outline", selected_tool="create_outline", reasoning_summary="The next chapter needs outline coverage first.", tool_args={"num_chapters": next_chapter}, should_continue=True)
            return AgentDecision(step=step, intent="write_next_chapter", selected_tool="auto_write_chapter", reasoning_summary="The user asked to continue writing the next chapter.", tool_args={"chapter_index": next_chapter}, should_continue=False)
        return AgentDecision(step=step, intent="show_status", selected_tool="show_status", reasoning_summary="Default to showing status when intent is unclear.", tool_args={}, should_continue=False)

    def _extract_chapter(self, text: str) -> int | None:
        """从用户消息文本中提取章节号。"""
        import re

        match = re.search(
            r"(?:第\s*)?(\d+)\s*(?:章|chapter|ch)?|(?:chapter|ch)\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        return int(match.group(1) or match.group(2)) if match else None
