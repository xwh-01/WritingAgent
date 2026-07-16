"""Typed, permission-aware tools available to the Story Orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import Field

from novelforge.core.exceptions import ConcurrentUpdateError
from novelforge.domain import (
    AgentRun,
    CandidateEvaluationRecord,
    CandidateStatus,
    ChapterCandidateRecord,
    DomainModel,
    utc_now,
)


class ToolResult(DomainModel):
    observation: str
    data: dict[str, Any] = Field(default_factory=dict)
    changed_story_revision: int | None = None
    candidate_id: str = ""
    requires_approval: bool = False
    error: str = ""


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    input_schema: dict[str, str]
    read_only: bool
    writes_canon: bool = False
    requires_approval: bool = False

    def as_catalog_item(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "read_only": self.read_only,
            "writes_canon": self.writes_canon,
            "requires_approval": self.requires_approval,
        }


class StoryAgentToolbox:
    """Expose application use cases without exposing repositories to agents."""

    SPECS = (
        AgentToolSpec("show_status", "读取故事当前状态", {}, True),
        AgentToolSpec(
            "create_outline",
            "确保大纲覆盖指定章节数量",
            {"num_chapters": "integer"},
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "plan_scenes",
            "为指定章节生成结构化场景计划",
            {"chapter_index": "integer"},
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "auto_write_chapter",
            "生成候选章节、执行质量门禁并在通过后提交",
            {"chapter_index": "integer"},
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "inspect_chapter",
            "读取正式章节及版本",
            {"chapter_index": "integer", "include_content": "boolean"},
            True,
        ),
        AgentToolSpec(
            "review_chapter",
            "执行章节质量评审",
            {"chapter_index": "integer"},
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "audit_continuity",
            "审计章节连续性",
            {"chapter_index": "integer"},
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "analyze_character_continuity",
            "审计人物跨章节状态轨迹",
            {
                "character": "string",
                "start_chapter": "integer",
                "end_chapter": "integer",
            },
            False,
            writes_canon=True,
        ),
        AgentToolSpec(
            "list_foreshadowings",
            "读取伏笔及其状态",
            {"status": "string"},
            True,
        ),
        AgentToolSpec(
            "revise_chapter",
            "生成修订候选提案但不覆盖正式正文",
            {"chapter_index": "integer", "revision_instruction": "string"},
            False,
            writes_canon=True,
            requires_approval=True,
        ),
        AgentToolSpec(
            "ask_user",
            "缺少关键参数时请求用户补充信息",
            {"question": "string"},
            True,
            requires_approval=True,
        ),
    )

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._handlers = {
            "show_status": self._show_status,
            "create_outline": self._create_outline,
            "plan_scenes": self._plan_scenes,
            "auto_write_chapter": self._auto_write_chapter,
            "inspect_chapter": self._inspect_chapter,
            "review_chapter": self._review_chapter,
            "audit_continuity": self._audit_continuity,
            "analyze_character_continuity": self._analyze_character_continuity,
            "list_foreshadowings": self._list_foreshadowings,
            "revise_chapter": self._revise_chapter,
            "ask_user": self._ask_user,
        }

    def catalog(self) -> list[dict[str, Any]]:
        return [spec.as_catalog_item() for spec in self.SPECS]

    def execute(self, name: str, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(observation="", error=f"Unknown tool: {name}")
        try:
            return handler(arguments, run)
        except Exception as exc:
            return ToolResult(
                observation=f"工具 {name} 执行失败。",
                changed_story_revision=self.engine.current_story.revision,
                error=str(exc),
            )

    def _show_status(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        story = self.engine.current_story
        return ToolResult(
            observation=(
                f"《{story.title}》当前为 {story.status}，正式章节 "
                f"{len(story.manuscript.chapters)} 章，故事版本 {story.revision}。"
            ),
            data={
                "story_id": str(story.id),
                "title": story.title,
                "status": story.status,
                "revision": story.revision,
                "current_chapter": story.current_chapter,
                "chapter_count": len(story.manuscript.chapters),
                "outline_count": len(story.design.outlines),
            },
            changed_story_revision=story.revision,
        )

    def _create_outline(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        target = max(1, int(arguments.get("num_chapters") or 1))
        outlines = self.engine.generate_outline(target)
        story = self.engine.current_story
        return ToolResult(
            observation=f"大纲已经覆盖 {len(outlines)} 章。",
            data={"outline_count": len(outlines)},
            changed_story_revision=story.revision,
        )

    def _plan_scenes(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        chapter = self.engine.generate_beats(chapter_index)
        return ToolResult(
            observation=f"第{chapter_index}章已经生成 {len(chapter.beats)} 个场景计划。",
            data={"chapter_index": chapter_index, "scene_count": len(chapter.beats)},
            changed_story_revision=self.engine.current_story.revision,
        )

    def _auto_write_chapter(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        contract = self.engine.ensure_chapter_contract(chapter_index)
        source = self.engine.current_story
        outline = source.get_outline(chapter_index)
        source_revision = source.revision
        outcome = self.engine.generation.generate(
            source,
            outline,
            contract,
            self.engine._polish_draft,
        )
        candidate = ChapterCandidateRecord(
            run_id=run.id,
            story_id=source.id,
            chapter_index=chapter_index,
            source_story_revision=source_revision,
            status=CandidateStatus.ACCEPTED if outcome.accepted else CandidateStatus.REJECTED,
            chapter=outcome.candidate,
        )
        self.engine.agent_run_repository.save_candidate(candidate)
        for assessment in outcome.assessments:
            self.engine.agent_run_repository.add_evaluation(
                CandidateEvaluationRecord(
                    candidate_id=candidate.id,
                    evaluator="chapter_acceptance_gate",
                    passed=assessment.decision == "accept",
                    score=assessment.score,
                    issues=list(assessment.reasons),
                    evidence={
                        "attempt": assessment.attempt,
                        "decision": assessment.decision,
                        "contract_checks": [
                            item.model_dump() for item in assessment.contract_checks
                        ],
                        "continuity": assessment.continuity.model_dump(),
                        "quality": assessment.quality.model_dump(),
                    },
                )
            )
        if not outcome.accepted:
            return ToolResult(
                observation=f"第{chapter_index}章候选稿未通过质量门禁。",
                data={"generation_report": outcome.to_report().model_dump()},
                candidate_id=str(candidate.id),
                changed_story_revision=source.revision,
                error="candidate_rejected",
            )

        try:
            committed = self.engine.chapter_workflow.commit(source, outcome)
        except ConcurrentUpdateError:
            candidate.status = CandidateStatus.STALE
            candidate.updated_at = utc_now()
            self.engine.agent_run_repository.save_candidate(candidate)
            raise
        self.engine.story = committed.story
        candidate.status = CandidateStatus.COMMITTED
        candidate.updated_at = committed.story.updated_at
        self.engine.agent_run_repository.save_candidate(candidate)
        return ToolResult(
            observation=(
                f"第{chapter_index}章通过质量门禁并已提交，"
                f"正文 {len(committed.chapter.content)} 字。"
            ),
            data={
                "chapter_index": chapter_index,
                "chapter_version": committed.chapter.version,
                "quality_score": outcome.final_assessment.score,
                "attempts": len(outcome.assessments),
            },
            candidate_id=str(candidate.id),
            changed_story_revision=committed.story.revision,
        )

    def _inspect_chapter(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        chapter = self.engine.current_story.require_chapter(chapter_index)
        include_content = bool(arguments.get("include_content", False))
        data: dict[str, Any] = {
            "chapter_index": chapter.index,
            "title": chapter.title,
            "version": chapter.version,
            "status": chapter.status,
            "character_count": len(chapter.content),
        }
        if include_content:
            data["content"] = chapter.content
        return ToolResult(
            observation=f"已读取第{chapter_index}章正式版本 {chapter.version}。",
            data=data,
            changed_story_revision=self.engine.current_story.revision,
        )

    def _review_chapter(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        report = self.engine.request_review(chapter_index)
        return ToolResult(
            observation=f"第{chapter_index}章评审完成，结论为 {report.verdict}。",
            data={"report": report.model_dump()},
            changed_story_revision=self.engine.current_story.revision,
        )

    def _audit_continuity(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        report = self.engine.audit_chapter_continuity(chapter_index)
        return ToolResult(
            observation=(
                f"第{chapter_index}章连续性审计完成，{'通过' if report.passed else '发现问题'}。"
            ),
            data={"report": report.model_dump()},
            changed_story_revision=self.engine.current_story.revision,
        )

    def _analyze_character_continuity(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        character = str(arguments.get("character") or "").strip()
        if not character:
            raise ValueError("character is required")
        start = max(1, int(arguments.get("start_chapter") or 1))
        end = max(start, int(arguments.get("end_chapter") or start))
        report = self.engine.audit_character_continuity(character, start, end)
        return ToolResult(
            observation=(
                f"{character} 的第{start}至{end}章连续性审计完成，"
                f"发现 {len(report.issues)} 个问题。"
            ),
            data={"report": report.model_dump()},
            changed_story_revision=self.engine.current_story.revision,
        )

    def _list_foreshadowings(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        status = str(arguments.get("status") or "").strip()
        items = self.engine.current_story.knowledge.foreshadowings
        if status:
            items = [item for item in items if str(item.status) == status]
        return ToolResult(
            observation=f"找到 {len(items)} 条符合条件的伏笔。",
            data={"foreshadowings": [item.model_dump() for item in items]},
            changed_story_revision=self.engine.current_story.revision,
        )

    def _revise_chapter(self, arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        chapter_index = self._chapter_index(arguments)
        instruction = str(arguments.get("revision_instruction") or "改善章节质量并保持故事事实一致")
        if chapter_index not in self.engine.current_story.quality.review_reports:
            self.engine.request_review(chapter_index)
        source_revision = self.engine.current_story.revision
        proposal = self.engine.create_revision_proposal(chapter_index, instruction)
        candidate = ChapterCandidateRecord(
            run_id=run.id,
            story_id=self.engine.current_story.id,
            chapter_index=chapter_index,
            source_story_revision=source_revision,
            status=CandidateStatus.ACCEPTED if proposal.eligible else CandidateStatus.REJECTED,
            chapter=self.engine.current_story.require_chapter(chapter_index).model_copy(
                deep=True,
                update={"content": proposal.proposed_content},
            ),
        )
        self.engine.agent_run_repository.save_candidate(candidate)
        self.engine.agent_run_repository.add_evaluation(
            CandidateEvaluationRecord(
                candidate_id=candidate.id,
                evaluator="revision_acceptance_gate",
                passed=proposal.eligible,
                issues=[
                    reason
                    for attempt in proposal.validation_report.attempts
                    for reason in attempt.reasons
                ],
                evidence={"validation_report": proposal.validation_report.model_dump()},
            )
        )
        eligible_message = (
            "正式正文尚未被覆盖，等待用户批准。"
            if proposal.eligible
            else "正式正文未被覆盖，但候选稿没有通过质量门禁。"
        )
        return ToolResult(
            observation=f"第{chapter_index}章修订提案 {proposal.id} 已生成，{eligible_message}",
            data={"proposal_id": proposal.id, "eligible": proposal.eligible},
            candidate_id=str(candidate.id),
            requires_approval=proposal.eligible,
            changed_story_revision=self.engine.current_story.revision,
            error="" if proposal.eligible else "revision_candidate_rejected",
        )

    @staticmethod
    def _ask_user(arguments: dict[str, Any], run: AgentRun) -> ToolResult:
        question = str(arguments.get("question") or "请补充完成任务所需的信息。")
        return ToolResult(observation=question, requires_approval=True)

    @staticmethod
    def _chapter_index(arguments: dict[str, Any]) -> int:
        chapter_index = int(arguments.get("chapter_index") or 0)
        if chapter_index < 1:
            raise ValueError("chapter_index must be at least 1")
        return chapter_index


__all__ = ["AgentToolSpec", "StoryAgentToolbox", "ToolResult"]
