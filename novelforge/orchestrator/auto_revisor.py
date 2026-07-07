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
from novelforge.orchestrator.trace import ERROR_QUALITY_GATE_FAILED, TraceRecorder, trace_timer


@dataclass
class AutoRevisorConfig:
    max_rounds: int = 5
    pass_threshold: float = 8.5
    quality_weights: dict[str, float] | None = None


class AutoRevisor:
    def __init__(
        self,
        story: Story,
        writer: WriterAgent,
        critic: CriticAgent,
        editor: EditorAgent,
        assembler: ContextAssembler,
        config: AutoRevisorConfig,
    ) -> None:
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
        self.stop_requested = True

    def run(self, chapter_index: int) -> AutoRevisionReport:
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

        for round_num in range(1, self.config.max_rounds + 1):
            if self.stop_requested:
                result.stopped = True
                break
            self.current_round = round_num
            self.status = f"reviewing_round_{round_num}"
            with trace_timer() as review_timer:
                review = self.critic.review_quality_scorecard(
                    current_content,
                    self.story.get_outline(chapter_index),
                    self.story,
                    self.assembler.assemble_writing_context(chapter_index, self.story),
                )
            total_score = review.total_score(self.config.quality_weights)
            recorder.record(
                stage="auto_revisor",
                action=f"review_round_{round_num}",
                input_summary=f"Review chapter {chapter_index} round {round_num}.",
                output_summary=f"Quality score={total_score:.2f}",
                observation=f"Round {round_num} review score {total_score:.2f}.",
                memory_hits_count=int(getattr(self.assembler, "last_context_stats", {}).get("memory_hits_count", 0) or 0),
                review_score_before=previous_score,
                review_score_after=total_score,
                success=total_score >= self.config.pass_threshold,
                error_type="" if total_score >= self.config.pass_threshold else ERROR_QUALITY_GATE_FAILED,
                error_message="" if total_score >= self.config.pass_threshold else "Quality score below pass threshold.",
                duration_ms=review_timer.duration_ms,
            )
            if total_score >= self.config.pass_threshold:
                result.rounds.append(
                    AutoRevisionRoundReport(
                        round=round_num,
                        review_report=review,
                        revised_content=current_content,
                        total_score=total_score,
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
            with trace_timer() as final_timer:
                final_review = self.critic.review_quality_scorecard(
                    current_content,
                    self.story.get_outline(chapter_index),
                    self.story,
                    self.assembler.assemble_writing_context(chapter_index, self.story),
                )
            result.final_score = final_review.total_score(self.config.quality_weights)
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
        chapter = self.story.chapters.get(chapter_index)
        if chapter and chapter.content:
            return chapter.content
        outline = self.story.get_outline(chapter_index)
        if chapter is None or not chapter.beats:
            chapter = Chapter(index=chapter_index, title=outline.title)
            self.story.chapters[chapter_index] = chapter
        context = self.assembler.assemble_writing_context(chapter_index, self.story)
        content = self.writer.write_chapter(chapter_index, outline, chapter.beats, context, self.story.style_guide)
        chapter.content = content
        chapter.summary = outline.summary
        chapter.status = "draft"
        return content

    def _summarize_revision(self, before: str, after: str, review: QualityReviewReport) -> str:
        issue_count = len(review.issues)
        length_delta = len(after) - len(before)
        if issue_count:
            dimensions = sorted({issue.dimension for issue in review.issues})
            return f"针对 {issue_count} 个问题修订，涉及：{', '.join(dimensions)}；字数变化 {length_delta:+d}。"
        return f"按评分卡进行整体润色；字数变化 {length_delta:+d}。"
