"""Use case that promotes only accepted chapter candidates into canonical state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from novelforge.application.commits import StoryCommitCoordinator
from novelforge.application.generation import ChapterGenerationPipeline, GenerationOutcome
from novelforge.application.story_domains import ManuscriptService, QualityService
from novelforge.core.exceptions import GenerationRejected
from novelforge.domain import Chapter, ChapterContract, Story, StoryStatus
from novelforge.longform.knowledge_pipeline import (
    ChapterKnowledgePipeline,
    ChapterKnowledgeResult,
)


@dataclass(frozen=True)
class ChapterWriteResult:
    story: Story
    chapter: Chapter
    generation: GenerationOutcome
    knowledge: ChapterKnowledgeResult


class ChapterWorkflow:
    """Generate, gate, commit, derive knowledge, persist, then rebuild projections."""

    def __init__(
        self,
        generation: ChapterGenerationPipeline,
        knowledge: ChapterKnowledgePipeline,
        manuscripts: ManuscriptService,
        quality: QualityService,
        commits: StoryCommitCoordinator,
    ) -> None:
        self.generation = generation
        self.knowledge = knowledge
        self.manuscripts = manuscripts
        self.quality = quality
        self.commits = commits

    def write(
        self,
        story: Story,
        chapter_index: int,
        contract: ChapterContract,
        polish_draft: Callable[[Story, int, str], str],
    ) -> ChapterWriteResult:
        source = story.model_copy(deep=True)
        outline = source.get_outline(chapter_index)
        outcome = self.generation.generate(source, outline, contract, polish_draft)
        report = outcome.to_report()

        if not outcome.accepted:
            rejected = story.model_copy(deep=True)
            self.quality.save_generation_report(rejected, report)
            rejected.touch()
            canonical = self.commits.save(rejected).story
            reasons = ", ".join(outcome.final_assessment.reasons) or "unknown gate failure"
            raise GenerationRejected(
                f"Chapter {chapter_index} was rejected: {reasons}",
                report=report,
                story=canonical,
            )

        return self.commit(story, outcome)

    def commit(self, story: Story, outcome: GenerationOutcome) -> ChapterWriteResult:
        """Promote an already accepted outcome through the only prose commit path."""
        if not outcome.accepted:
            raise ValueError("Cannot commit a rejected chapter candidate.")
        report = outcome.to_report()
        working = story.model_copy(deep=True)
        self.quality.invalidate_chapter_assessments(working, outcome.candidate.index)
        committed = self.manuscripts.commit_candidate(working, outcome.candidate)
        knowledge = self.knowledge.process(working, committed)
        self.quality.save_generation_report(working, report)
        self.quality.save_continuity_report(
            working,
            committed.index,
            outcome.final_assessment.continuity,
        )
        working.status = StoryStatus.REVIEWING
        working.touch()
        canonical = self.commits.save_and_reindex(
            working,
            event_type="chapter_committed",
        ).story
        return ChapterWriteResult(
            canonical,
            canonical.require_chapter(committed.index),
            outcome,
            knowledge,
        )


__all__ = ["ChapterWorkflow", "ChapterWriteResult"]
