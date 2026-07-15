"""Explicit user edits and AI revision proposals."""

from __future__ import annotations

from dataclasses import dataclass

from novelforge.application.chapter_workflow import ChapterWorkflow
from novelforge.application.commits import StoryCommitCoordinator
from novelforge.application.generation import ChapterGenerationPipeline
from novelforge.application.story_domains import ManuscriptService, QualityService
from novelforge.core.exceptions import GenerationRejected, WorkflowError
from novelforge.domain import (
    Chapter,
    ChapterStatus,
    ProposalStatus,
    RevisionProposal,
    Story,
    StoryStatus,
    utc_now,
)
from novelforge.longform.knowledge_pipeline import ChapterKnowledgePipeline


@dataclass(frozen=True)
class ChapterEditResult:
    story: Story
    chapter: Chapter


@dataclass(frozen=True)
class ProposalResult:
    story: Story
    proposal: RevisionProposal


class ChapterEditingService:
    """Separate trusted user edits from approval-gated generated revisions."""

    def __init__(
        self,
        editor,
        generation: ChapterGenerationPipeline,
        workflow: ChapterWorkflow,
        knowledge: ChapterKnowledgePipeline,
        manuscripts: ManuscriptService,
        quality: QualityService,
        commits: StoryCommitCoordinator,
    ) -> None:
        self.editor = editor
        self.generation = generation
        self.workflow = workflow
        self.knowledge = knowledge
        self.manuscripts = manuscripts
        self.quality = quality
        self.commits = commits

    def save_user_content(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        title: str | None = None,
        status: ChapterStatus | str = ChapterStatus.DRAFT,
    ) -> ChapterEditResult:
        if not content.strip():
            raise WorkflowError("Chapter content cannot be empty.")
        working = story.model_copy(deep=True)
        outline = working.get_outline(chapter_index)
        current = working.get_chapter(chapter_index)
        candidate = Chapter(
            index=chapter_index,
            title=title or (current.title if current else outline.title),
            content=content.strip(),
            status=ChapterStatus(status),
            summary=(current.summary if current else outline.summary),
            beats=(current.beats if current else []),
        )
        committed = self.manuscripts.commit_user_edit(working, candidate)
        self.quality.invalidate_chapter_assessments(working, chapter_index)
        self.knowledge.process(working, committed)
        working.status = StoryStatus.DRAFTING
        working.touch()
        canonical = self.commits.save_and_reindex(
            working,
            event_type="user_chapter_edited",
        ).story
        return ChapterEditResult(canonical, canonical.require_chapter(chapter_index))

    def create_proposal(
        self,
        story: Story,
        chapter_index: int,
        instruction: str,
    ) -> ProposalResult:
        clean_instruction = instruction.strip()
        if not clean_instruction:
            raise WorkflowError("Revision instruction cannot be empty.")
        source = story.require_chapter(chapter_index)
        if not source.content.strip():
            raise WorkflowError(f"Chapter {chapter_index} has no committed prose.")
        review = story.quality.review_reports.get(chapter_index)
        if review is None:
            raise WorkflowError("Review the chapter before creating a revision proposal.")
        outline = story.get_outline(chapter_index)
        contract = story.design.chapter_contracts.get(chapter_index)
        if contract is None:
            raise WorkflowError(f"Chapter {chapter_index} has no acceptance contract.")
        revised = self.editor.revise_chapter(
            source.content,
            review,
            story.style_guide,
            revision_instruction=clean_instruction,
        ).strip()
        candidate = source.model_copy(
            deep=True,
            update={"content": revised, "status": ChapterStatus.REVISED},
        )
        outcome = self.generation.gate(story, outline, contract, candidate)
        proposal = RevisionProposal(
            story_id=str(story.id),
            chapter_index=chapter_index,
            source_version=source.version,
            instruction=clean_instruction,
            original_content=source.content,
            proposed_content=outcome.candidate.content,
            review_report=review,
            validation_report=outcome.to_report(),
            eligible=outcome.accepted,
        )
        working = story.model_copy(deep=True)
        self.quality.add_proposal(working, proposal)
        working.touch()
        canonical = self.commits.save(working).story
        saved = self.quality.get_proposal(canonical, proposal.id)
        assert saved is not None
        return ProposalResult(canonical, saved)

    def accept_proposal(self, story: Story, proposal_id: str) -> ChapterEditResult:
        proposal = self._pending(story, proposal_id)
        if not proposal.eligible:
            raise GenerationRejected(
                "The revision proposal did not pass the chapter acceptance gates.",
                report=proposal.validation_report,
                story=story,
            )
        source = story.require_chapter(proposal.chapter_index)
        if source.version != proposal.source_version:
            raise WorkflowError("The chapter changed after this proposal was created.")
        outline = story.get_outline(proposal.chapter_index)
        contract = story.design.chapter_contracts[proposal.chapter_index]
        candidate = source.model_copy(
            deep=True,
            update={
                "content": proposal.proposed_content,
                "status": ChapterStatus.REVISED,
            },
        )
        outcome = self.generation.gate(story, outline, contract, candidate)
        if not outcome.accepted:
            raise GenerationRejected(
                "The revision no longer passes current acceptance gates.",
                report=outcome.to_report(),
                story=story,
            )
        working = story.model_copy(deep=True)
        saved = self._pending(working, proposal_id)
        saved.status = ProposalStatus.ACCEPTED
        saved.updated_at = utc_now()
        result = self.workflow.commit(working, outcome)
        return ChapterEditResult(result.story, result.chapter)

    def reject_proposal(self, story: Story, proposal_id: str) -> ProposalResult:
        working = story.model_copy(deep=True)
        proposal = self._pending(working, proposal_id)
        proposal.status = ProposalStatus.REJECTED
        proposal.updated_at = utc_now()
        working.touch()
        canonical = self.commits.save(working).story
        saved = self.quality.get_proposal(canonical, proposal_id)
        assert saved is not None
        return ProposalResult(canonical, saved)

    def get_proposal(self, story: Story, proposal_id: str) -> RevisionProposal | None:
        return self.quality.get_proposal(story, proposal_id)

    def finalize(self, story: Story, chapter_index: int) -> ChapterEditResult:
        working = story.model_copy(deep=True)
        chapter = working.require_chapter(chapter_index)
        if not chapter.content.strip():
            raise WorkflowError(f"Chapter {chapter_index} has no committed prose.")
        chapter.status = ChapterStatus.FINALIZED
        working.status = StoryStatus.FINALIZED
        working.touch()
        canonical = self.commits.save(working).story
        return ChapterEditResult(canonical, canonical.require_chapter(chapter_index))

    def _pending(self, story: Story, proposal_id: str) -> RevisionProposal:
        proposal = self.quality.get_proposal(story, proposal_id)
        if proposal is None:
            raise WorkflowError(f"Revision proposal not found: {proposal_id}")
        if proposal.status is not ProposalStatus.AWAITING_APPROVAL:
            raise WorkflowError(f"Revision proposal is already {proposal.status}.")
        return proposal


__all__ = ["ChapterEditingService", "ChapterEditResult", "ProposalResult"]
