"""Read and persist chapter quality reviews without changing prose."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from novelforge.application.commits import StoryCommitCoordinator
from novelforge.application.story_domains import QualityService
from novelforge.core.exceptions import WorkflowError
from novelforge.domain import (
    CharacterContinuityReport,
    ConstraintCheck,
    ContinuityAuditReport,
    ReviewReport,
    Story,
)


class ReviewContextPort(Protocol):
    def build(self, chapter_index: int, story: Story) -> str: ...


class CriticPort(Protocol):
    def review_chapter(self, content, outline, characters, knowledge, context): ...


class ContractValidatorPort(Protocol):
    def validate(self, content, contract) -> list[ConstraintCheck]: ...


class ContinuityPort(Protocol):
    def audit_chapter(self, story, chapter_index, content, context): ...


class CharacterAuditPort(Protocol):
    def audit(self, story, character, start_chapter, end_chapter): ...


class ConsistencyPort(Protocol):
    def review_chapter_consistency(self, story, chapter_index, content): ...


@dataclass(frozen=True)
class ReviewResult:
    story: Story
    report: ReviewReport


@dataclass(frozen=True)
class ContinuityResult:
    story: Story
    report: ContinuityAuditReport


@dataclass(frozen=True)
class CharacterAuditResult:
    story: Story
    report: CharacterContinuityReport


class ChapterReviewService:
    """Own review, contract validation, and continuity audit use cases."""

    def __init__(
        self,
        context: ReviewContextPort,
        critic: CriticPort,
        contracts: ContractValidatorPort,
        continuity: ContinuityPort,
        character_auditor: CharacterAuditPort,
        consistency: ConsistencyPort,
        quality: QualityService,
        commits: StoryCommitCoordinator,
    ) -> None:
        self.context = context
        self.critic = critic
        self.contracts = contracts
        self.continuity = continuity
        self.character_auditor = character_auditor
        self.consistency = consistency
        self.quality = quality
        self.commits = commits

    def review(self, story: Story, chapter_index: int) -> ReviewResult:
        working = story.model_copy(deep=True)
        chapter = self._chapter_with_content(working, chapter_index)
        outline = working.get_outline(chapter_index)
        context = self.context.build(chapter_index, working)
        report = self.critic.review_chapter(
            chapter.content,
            outline,
            list(working.design.characters.values()),
            [],
            context,
        )
        consistency = self.consistency.review_chapter_consistency(
            working,
            chapter_index,
            chapter.content,
        )
        report.logic_issues.extend(consistency.get("foreshadowing_issues", []))
        report.pacing_issues.extend(consistency.get("pacing_issues", []))
        report.character_issues.extend(consistency.get("character_state_issues", []))
        self.quality.save_review_report(working, chapter_index, report)
        working.touch()
        canonical = self.commits.save(working).story
        return ReviewResult(canonical, report)

    def validate_contract(self, story: Story, chapter_index: int) -> list[ConstraintCheck]:
        chapter = self._chapter_with_content(story, chapter_index)
        contract = story.design.chapter_contracts.get(chapter_index)
        if contract is None:
            raise WorkflowError(f"Chapter {chapter_index} has no acceptance contract.")
        return self.contracts.validate(chapter.content, contract)

    def audit_continuity(self, story: Story, chapter_index: int) -> ContinuityResult:
        working = story.model_copy(deep=True)
        chapter = self._chapter_with_content(working, chapter_index)
        context = self.context.build(chapter_index, working)
        report = self.continuity.audit_chapter(
            working,
            chapter_index,
            chapter.content,
            context,
        )
        self.quality.save_continuity_report(working, chapter_index, report)
        working.touch()
        canonical = self.commits.save(working).story
        return ContinuityResult(canonical, report)

    def audit_character(
        self,
        story: Story,
        character_query: str,
        start_chapter: int,
        end_chapter: int,
    ) -> CharacterAuditResult:
        if end_chapter < start_chapter:
            raise WorkflowError("end_chapter must be greater than or equal to start_chapter.")
        query = character_query.strip().lower()
        matches = [
            character
            for character in story.design.characters.values()
            if query in {character.id.lower(), character.name.lower()}
        ]
        if len(matches) != 1:
            reason = "not found" if not matches else "ambiguous"
            raise WorkflowError(f"Character '{character_query}' is {reason}.")
        working = story.model_copy(deep=True)
        report = self.character_auditor.audit(
            working,
            matches[0],
            start_chapter,
            end_chapter,
        )
        self.quality.save_character_continuity_report(working, report)
        working.touch()
        canonical = self.commits.save(working).story
        return CharacterAuditResult(canonical, report)

    @staticmethod
    def _chapter_with_content(story: Story, chapter_index: int):
        chapter = story.get_chapter(chapter_index)
        if chapter is None or not chapter.content.strip():
            raise WorkflowError(f"Chapter {chapter_index} has no committed prose.")
        return chapter


__all__ = [
    "ChapterReviewService",
    "CharacterAuditResult",
    "ContinuityResult",
    "ReviewResult",
]
