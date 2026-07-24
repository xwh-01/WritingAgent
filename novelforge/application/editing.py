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
    ScenePatch,
    Story,
    StoryStatus,
    content_digest,
    utc_now,
)
from novelforge.longform.knowledge_pipeline import ChapterKnowledgePipeline
from novelforge.storage.agent_runs import AgentRunRepository


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
        proposals: AgentRunRepository,
    ) -> None:
        self.editor = editor
        self.generation = generation
        self.workflow = workflow
        self.knowledge = knowledge
        self.manuscripts = manuscripts
        self.quality = quality
        self.commits = commits
        self.proposals = proposals

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
        # A trusted free-form user replacement has no reliable scene diff. Drop
        # the derived scene projection rather than keeping stale scene prose;
        # future AI revisions will re-plan it into patches before mutating it.
        retained_beats = (
            [item.model_copy(deep=True) for item in current.beats]
            if current is not None and current.content.strip() == content.strip()
            else []
        )
        candidate = Chapter(
            index=chapter_index,
            title=title or (current.title if current else outline.title),
            content=content.strip(),
            status=ChapterStatus(status),
            summary=(current.summary if current else outline.summary),
            beats=retained_beats,
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
        proposal_patches: list[ScenePatch] = []
        if source.beats:
            revise_scenes = getattr(self.editor, "revise_scenes_from_review_report", None)
            if not callable(revise_scenes):
                raise WorkflowError("Structured chapter revisions require the ScenePatch editor protocol.")
            patches = revise_scenes(
                source.beats,
                review,
                story.style_guide,
                revision_instruction=clean_instruction,
            )
            if not patches:
                raise WorkflowError("Revision proposal produced no scene patches.")
            candidate = self.generation.apply_scene_patches(source, patches)
            candidate.status = ChapterStatus.REVISED
            proposal_patches = self._applied_patches(source, candidate)
        else:
            # Unstructured legacy/user-authored chapters have no scene source
            # to patch. Keep this compatibility branch isolated from generated
            # chapters, which always use the ScenePatch protocol above.
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
            scene_patches=proposal_patches,
            review_report=review,
            validation_report=outcome.to_report(),
            eligible=outcome.accepted,
        )
        saved = self.proposals.save_revision_proposal(proposal)
        return ProposalResult(story, saved)

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
            proposal.status = ProposalStatus.REJECTED
            proposal.updated_at = utc_now()
            self.proposals.save_revision_proposal(proposal)
            raise WorkflowError("The chapter changed after this proposal was created.")
        outline = story.get_outline(proposal.chapter_index)
        contract = story.design.chapter_contracts[proposal.chapter_index]
        if source.beats:
            if not proposal.scene_patches:
                raise WorkflowError("Structured revision proposal has no ScenePatch evidence.")
            candidate = self.generation.apply_scene_patches(source, proposal.scene_patches)
            candidate.status = ChapterStatus.REVISED
        else:
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
        result = self.workflow.commit(story, outcome)
        proposal.status = ProposalStatus.ACCEPTED
        proposal.updated_at = utc_now()
        self.proposals.save_revision_proposal(proposal)
        return ChapterEditResult(result.story, result.chapter)

    def reject_proposal(self, story: Story, proposal_id: str) -> ProposalResult:
        proposal = self._pending(story, proposal_id)
        proposal.status = ProposalStatus.REJECTED
        proposal.updated_at = utc_now()
        saved = self.proposals.save_revision_proposal(proposal)
        return ProposalResult(story, saved)

    def get_proposal(self, story: Story, proposal_id: str) -> RevisionProposal | None:
        try:
            proposal = self.proposals.load_revision_proposal(proposal_id)
        except FileNotFoundError:
            return None
        return proposal if proposal.story_id == str(story.id) else None

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
        proposal = self.get_proposal(story, proposal_id)
        if proposal is None:
            raise WorkflowError(f"Revision proposal not found: {proposal_id}")
        if proposal.status is not ProposalStatus.AWAITING_APPROVAL:
            raise WorkflowError(f"Revision proposal is already {proposal.status}.")
        return proposal

    @staticmethod
    def _applied_patches(source: Chapter, candidate: Chapter) -> list[ScenePatch]:
        original = {item.scene_index: item for item in source.beats}
        return [
            ScenePatch(
                scene_index=scene.scene_index,
                content=scene.content,
                ending_state=scene.end_state,
                reason="approval_gated_revision",
                source_content_digest=content_digest(original[scene.scene_index].content),
            )
            for scene in candidate.beats
            if scene.scene_index in original
            and (
                scene.content != original[scene.scene_index].content
                or scene.end_state != original[scene.scene_index].end_state
            )
        ]


__all__ = ["ChapterEditingService", "ChapterEditResult", "ProposalResult"]
