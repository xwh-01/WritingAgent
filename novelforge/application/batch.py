"""Sequential batch writing built from the same reliable chapter use case."""

from __future__ import annotations

from typing import Callable

from novelforge.application.chapter_workflow import ChapterWorkflow
from novelforge.application.planning import StoryPlanningService
from novelforge.core.exceptions import GenerationRejected
from novelforge.domain import BatchChapterResult, BatchWriteReport, Story


class BatchWritingService:
    """Write a range in order; every chapter uses the normal acceptance gates."""

    def __init__(
        self,
        planning: StoryPlanningService,
        chapters: ChapterWorkflow,
    ) -> None:
        self.planning = planning
        self.chapters = chapters

    def write_range(
        self,
        story: Story,
        start_chapter: int,
        end_chapter: int,
        polish_draft: Callable,
    ) -> tuple[Story, BatchWriteReport]:
        if start_chapter < 1 or end_chapter < start_chapter:
            raise ValueError("Invalid chapter range.")
        current = self.planning.outline(story, end_chapter)
        report = BatchWriteReport(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        for chapter_index in range(start_chapter, end_chapter + 1):
            try:
                contract_result = self.planning.ensure_contract(current, chapter_index)
                current = contract_result.story
                result = self.chapters.write(
                    current,
                    chapter_index,
                    contract_result.contract,
                    polish_draft,
                )
                current = result.story
                chapter = result.chapter
                report.results.append(
                    BatchChapterResult(
                        chapter_index=chapter_index,
                        status="completed",
                        title=chapter.title,
                        character_count=len(chapter.content),
                        quality_score=result.generation.final_assessment.score,
                    )
                )
                report.completed += 1
            except GenerationRejected as exc:
                if isinstance(exc.story, Story):
                    current = exc.story
                report.results.append(
                    BatchChapterResult(
                        chapter_index=chapter_index,
                        status="rejected",
                        message=str(exc),
                    )
                )
                report.failed += 1
                break
            except Exception as exc:
                report.results.append(
                    BatchChapterResult(
                        chapter_index=chapter_index,
                        status="failed",
                        message=str(exc),
                    )
                )
                report.failed += 1
                break

        return current, report


__all__ = ["BatchWritingService"]
