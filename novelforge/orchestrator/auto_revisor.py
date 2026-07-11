"""Autonomous iterative review and repair loop."""

from __future__ import annotations

from dataclasses import dataclass

from novelforge.agents.critic import CriticAgent
from novelforge.agents.editor import EditorAgent
from novelforge.agents.writer import WriterAgent
from novelforge.context.assembler import ContextAssembler
from novelforge.core.models import (
    AutoRevisionReport,
    AutoRevisionRoundReport,
    Chapter,
    QualityReviewReport,
    RevisionIssue,
    Story,
)
from novelforge.validation import ChapterContractValidator
from novelforge.orchestrator.trace import ERROR_QUALITY_GATE_FAILED, TraceRecorder, trace_timer


@dataclass
class AutoRevisorConfig:
    """自动修订器配置：最大轮次、通过阈值、采样数和品质评分权重。"""
    max_rounds: int = 5
    pass_threshold: float = 8.5
    score_samples: int = 3
    quality_weights: dict[str, float] | None = None


class AutoRevisor:
    """自主迭代审阅和修订循环器：写作→评审→修订，直至品质达标或达到最大轮次。"""

    def __init__(
        self,
        story: Story,
        writer: WriterAgent,
        critic: CriticAgent,
        editor: EditorAgent,
        assembler: ContextAssembler,
        config: AutoRevisorConfig,
    ) -> None:
        """初始化修订器，注入故事对象、写作/评审/编辑智能体和上下文装配器。"""
        self.story = story
        self.writer = writer
        self.critic = critic
        self.editor = editor
        self.assembler = assembler
        self.config = config
        self.stop_requested = False
        self.current_round = 0
        self.status = "idle"

    def request_stop(self) -> None:
        """设置停止标志，请求在下一次循环检查时中止修订。"""
        self.stop_requested = True

    def run(self, chapter_index: int, continuity_issues: list | None = None) -> AutoRevisionReport:
        """执行自动修订主循环：生成初稿、逐轮评审→修订，直至通过或达到最大轮次。

        Args:
            chapter_index: 章节编号。
            continuity_issues: 可选的连续性审计问题列表（ContinuityIssue），
                               将注入到每轮修订的 QualityReviewReport 中。
        """
        import statistics

        self.status = "writing"
        self.stop_requested = False
        recorder = TraceRecorder(
            run_id=f"auto-revisor:{self.story.id}:ch{chapter_index}",
            story_id=str(self.story.id),
            chapter_index=chapter_index,
        )
        with trace_timer() as draft_timer:
            current_content = self._initial_draft(chapter_index)
        result = AutoRevisionReport(chapter_index=chapter_index, final_content=current_content)
        recorder.record(
            stage="auto_revisor",
            action="initial_draft",
            input_summary=f"Prepare chapter {chapter_index} draft for review loop.",
            output_summary=f"Initial content chars={len(current_content)}",
            observation="Initial draft ready.",
            memory_hits_count=int(getattr(self.assembler, "last_context_stats", {}).get("memory_hits_count", 0) or 0),
            duration_ms=draft_timer.duration_ms,
        )
        previous_score: float | None = None
        contract_validator = ChapterContractValidator(getattr(self.critic, "llm", None))
        contract = self.story.chapter_contracts.get(chapter_index)

        for round_num in range(1, self.config.max_rounds + 1):
            if self.stop_requested:
                result.stopped = True
                break
            self.current_round = round_num
            self.status = f"reviewing_round_{round_num}"

            # ── Multi-sample scoring ──
            samples = max(1, self.config.score_samples)
            sample_scores: list[QualityReviewReport] = []
            sample_totals: list[float] = []
            with trace_timer() as review_timer:
                assembled_ctx = self.assembler.assemble_writing_context(chapter_index, self.story)
                for _ in range(samples):
                    sample = self.critic.review_quality_scorecard(
                        current_content,
                        self.story.get_outline(chapter_index),
                        self.story,
                        assembled_ctx,
                    )
                    sample_scores.append(sample)
                    sample_totals.append(sample.total_score(self.config.quality_weights))

            # Use median of each dimension across samples
            if samples > 1:
                review = sample_scores[0]
                review.scores.logic_consistency = round(statistics.median(
                    [s.scores.logic_consistency for s in sample_scores]), 2)
                review.scores.character_fidelity = round(statistics.median(
                    [s.scores.character_fidelity for s in sample_scores]), 2)
                review.scores.foreshadowing_handling = round(statistics.median(
                    [s.scores.foreshadowing_handling for s in sample_scores]), 2)
                review.scores.pacing = round(statistics.median(
                    [s.scores.pacing for s in sample_scores]), 2)
                review.scores.style_uniformity = round(statistics.median(
                    [s.scores.style_uniformity for s in sample_scores]), 2)
                # Merge unique issues from all samples
                seen_descs = set()
                merged_issues = []
                for s in sample_scores:
                    for issue in s.issues:
                        if issue.description not in seen_descs:
                            seen_descs.add(issue.description)
                            merged_issues.append(issue)
                review.issues = merged_issues
                review.overall_comment = f"{samples}-sample median review: " + review.overall_comment
            else:
                review = sample_scores[0]

            total_score = review.total_score(self.config.quality_weights)
            score_variance = round(statistics.variance(sample_totals), 4) if len(sample_totals) > 1 else 0.0

            # Hard requirements are evaluated before the numeric quality gate.
            review.contract_checks = contract_validator.validate(current_content, contract)
            review.hard_constraints_passed = contract_validator.hard_constraints_passed(review.contract_checks)
            from novelforge.core.models import RevisionIssue as RevIssue
            for check in review.contract_checks:
                if not check.passed:
                    review.issues.append(RevIssue(
                        dimension=f"contract:{check.constraint_type}",
                        severity=check.severity,
                        description=check.message or check.requirement,
                        evidence=check.evidence,
                    ))

            # Continuity is also a hard gate; inject it before deciding pass/fail.
            if continuity_issues:
                for ci in continuity_issues:
                    severity = ci.get("severity", "medium") if isinstance(ci, dict) else getattr(ci, "severity", "medium")
                    description = ci.get("description", "") if isinstance(ci, dict) else getattr(ci, "description", "")
                    dimension = ci.get("dimension", "unknown") if isinstance(ci, dict) else getattr(ci, "dimension", "unknown")
                    evidence = ci.get("evidence", "") if isinstance(ci, dict) else getattr(ci, "evidence", "")
                    review.issues.append(RevIssue(
                        dimension=f"continuity:{dimension}", severity=severity,
                        description=description, evidence=evidence,
                    ))
                    if severity in {"high", "critical"}:
                        review.hard_constraints_passed = False

            passed_gate = total_score >= self.config.pass_threshold and review.hard_constraints_passed

            recorder.record(
                stage="auto_revisor",
                action=f"review_round_{round_num}",
                input_summary=f"Review chapter {chapter_index} round {round_num} ({samples} samples).",
                output_summary=f"Quality score={total_score:.2f} (median of {samples}, variance={score_variance:.4f})",
                observation=f"Round {round_num} review score {total_score:.2f}.",
                memory_hits_count=int(getattr(self.assembler, "last_context_stats", {}).get("memory_hits_count", 0) or 0),
                review_score_before=previous_score,
                review_score_after=total_score,
                success=passed_gate,
                error_type="" if passed_gate else ERROR_QUALITY_GATE_FAILED,
                error_message="" if passed_gate else (
                    f"Quality score {total_score:.2f}; hard_constraints_passed={review.hard_constraints_passed}"
                    + (f" (variance={score_variance:.4f}, evaluator may be unstable)" if score_variance > 2.0 else "")
                ),
                duration_ms=review_timer.duration_ms,
            )
            if passed_gate:
                result.rounds.append(
                    AutoRevisionRoundReport(
                        round=round_num,
                        review_report=review,
                        revised_content=current_content,
                        total_score=total_score,
                        review_score_variance=score_variance,
                        modification_summary="达到通过阈值，无需继续修订。",
                    )
                )
                result.passed = True
                result.final_score = total_score
                result.final_content = current_content
                break

            self.status = f"revising_round_{round_num}"
            with trace_timer() as revise_timer:
                revised = self.editor.revise_from_quality_report(current_content, review, self.story.style_guide)
            result.rounds.append(
                AutoRevisionRoundReport(
                    round=round_num,
                    review_report=review,
                    revised_content=revised,
                    total_score=total_score,
                    review_score_variance=score_variance,
                    modification_summary=self._summarize_revision(current_content, revised, review),
                )
            )
            current_content = revised
            recorder.record(
                stage="auto_revisor",
                action=f"revise_round_{round_num}",
                input_summary=f"Revise chapter {chapter_index} after score {total_score:.2f}.",
                output_summary=f"Revised chars={len(revised)}",
                observation=result.rounds[-1].modification_summary,
                memory_hits_count=int(getattr(self.assembler, "last_context_stats", {}).get("memory_hits_count", 0) or 0),
                review_score_before=total_score,
                review_score_after=None,
                duration_ms=revise_timer.duration_ms,
            )
            previous_score = total_score

        if not result.passed and not result.stopped:
            assembled_ctx = self.assembler.assemble_writing_context(chapter_index, self.story)
            with trace_timer() as final_timer:
                final_review = self.critic.review_quality_scorecard(
                    current_content,
                    self.story.get_outline(chapter_index),
                    self.story,
                    assembled_ctx,
                )
            result.final_score = final_review.total_score(self.config.quality_weights)
            final_review.contract_checks = contract_validator.validate(current_content, contract)
            final_review.hard_constraints_passed = contract_validator.hard_constraints_passed(final_review.contract_checks)
            for check in final_review.contract_checks:
                if not check.passed:
                    final_review.issues.append(RevisionIssue(
                        dimension=f"contract:{check.constraint_type}",
                        severity=check.severity,
                        description=check.message or check.requirement,
                        evidence=check.evidence,
                    ))
            result.final_content = current_content
            result.residual_issues = final_review.issues
            recorder.record(
                stage="auto_revisor",
                action="final_review",
                input_summary=f"Final review for chapter {chapter_index}.",
                output_summary=f"Final score={result.final_score:.2f}",
                observation=f"Final score {result.final_score:.2f}; passed={result.final_score >= self.config.pass_threshold}.",
                memory_hits_count=int(getattr(self.assembler, "last_context_stats", {}).get("memory_hits_count", 0) or 0),
                review_score_before=previous_score,
                review_score_after=result.final_score,
                success=result.final_score >= self.config.pass_threshold,
                error_type="" if result.final_score >= self.config.pass_threshold else ERROR_QUALITY_GATE_FAILED,
                error_message="" if result.final_score >= self.config.pass_threshold else "Final score below pass threshold.",
                duration_ms=final_timer.duration_ms,
            )
            if not result.residual_issues:
                result.residual_issues = [
                    RevisionIssue(
                        dimension="综合质量",
                        severity="medium",
                        description=f"最终评分 {result.final_score:.2f} 未达到通过阈值 {self.config.pass_threshold:.2f}。",
                    )
                ]
        elif result.stopped:
            result.final_content = current_content
            result.residual_issues = [RevisionIssue(dimension="流程", severity="medium", description="用户请求中止自动修订循环。")]

        self.status = "passed" if result.passed else "stopped" if result.stopped else "finished_with_residual_issues"
        result.trace_events = [event.model_dump() for event in recorder.events]
        return result

    def _initial_draft(self, chapter_index: int) -> str:
        """获取或生成指定章节的初稿内容作为修订循环的起点。"""
        chapter = self.story.chapters.get(chapter_index)
        if chapter and chapter.content:
            return chapter.content
        outline = self.story.get_outline(chapter_index)
        if chapter is None or not chapter.beats:
            chapter = Chapter(index=chapter_index, title=outline.title)
            self.story.chapters[chapter_index] = chapter
        context = self.assembler.assemble_writing_context(chapter_index, self.story)
        content = self.writer.write_chapter(
            chapter_index, outline, chapter.beats, context, self.story.style_guide,
            contract=self.story.chapter_contracts.get(chapter_index),
        )
        chapter.content = content
        chapter.summary = outline.summary
        chapter.status = "draft"
        return content

    def _summarize_revision(self, before: str, after: str, review: QualityReviewReport) -> str:
        """生成本轮修订的摘要文本，说明涉及的问题维度和字数变化。"""
        issue_count = len(review.issues)
        length_delta = len(after) - len(before)
        if issue_count:
            dimensions = sorted({issue.dimension for issue in review.issues})
            return f"针对 {issue_count} 个问题修订，涉及：{', '.join(dimensions)}；字数变化 {length_delta:+d}。"
        return f"按评分卡进行整体润色；字数变化 {length_delta:+d}。"
