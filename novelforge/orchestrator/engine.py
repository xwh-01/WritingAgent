"""Thin application facade used by the CLI and HTTP adapters."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from novelforge.agents import (
    CharacterArcAuditorAgent,
    ContinuityAuditorAgent,
    CriticAgent,
    EditorAgent,
    PlannerAgent,
    StoryOrchestratorAgent,
    WriterAgent,
)
from novelforge.application import (
    BatchWritingService,
    CandidateEvaluator,
    ChapterEditingService,
    ChapterGenerationPipeline,
    ChapterReviewService,
    ChapterWorkflow,
    DesignService,
    GenerationPolicy,
    KnowledgeService,
    ManuscriptService,
    QualityService,
    StoryCommitCoordinator,
    StoryPlanningService,
)
from novelforge.application.bootstrap import build_storage_runtime
from novelforge.context.writing import WritingContextAssembler
from novelforge.core.config import AppConfig, load_config
from novelforge.core.exceptions import GenerationRejected
from novelforge.domain import (
    AgentRun,
    BatchWriteReport,
    Chapter,
    ChapterContract,
    ChapterStatus,
    Character,
    CharacterContinuityReport,
    CharacterFact,
    ConstraintCheck,
    ContinuityAuditReport,
    ReviewReport,
    RevisionProposal,
    Story,
    WorldSetting,
)
from novelforge.llm import build_llm_client
from novelforge.longform.knowledge_pipeline import ChapterKnowledgePipeline
from novelforge.longform.knowledge_system import StoryKnowledgeSystem
from novelforge.orchestrator.chapter_composer import ChapterComposer
from novelforge.orchestrator.runtime import StoryAgentRuntime
from novelforge.orchestrator.tools import StoryAgentToolbox
from novelforge.validation import ChapterContractValidator


class NovelForgeEngine:
    """Compose dependencies and expose use cases without owning domain rules."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.llm = build_llm_client(self.config.llm)

        runtime = build_storage_runtime(self.config.storage, self.config.indexes)
        self.repository = runtime.repository
        self.agent_run_repository = runtime.agent_runs
        self.artifact_store = runtime.artifacts
        self.vector_store = runtime.vector_index
        self.graph_store = runtime.graph_index
        self.text_store = runtime.full_text_index
        self.index_service = runtime.indexes
        self.export_service = runtime.exports
        self.storage_service = runtime.storage

        self.knowledge_system = StoryKnowledgeSystem(
            self.llm,
            retrieval_config=self.config.retrieval,
        )
        self.knowledge_pipeline = ChapterKnowledgePipeline(self.knowledge_system)
        self.writing_context = WritingContextAssembler(
            self.vector_store,
            self.text_store,
            self.config.story.max_context_tokens,
            self.knowledge_system,
            retrieval_config=self.config.retrieval,
        )

        self.planner = PlannerAgent(self.llm)
        self.story_orchestrator = StoryOrchestratorAgent(self.llm)
        self.writer = WriterAgent(self.llm)
        self.critic = CriticAgent(self.llm)
        self.editor = EditorAgent(self.llm)
        self.continuity_auditor = ContinuityAuditorAgent(self.llm)
        self.character_auditor = CharacterArcAuditorAgent(self.llm)
        self.contract_validator = ChapterContractValidator(self.llm)
        self.chapter_composer = ChapterComposer(
            planner=self.planner,
            writer=self.writer,
            target_length=self.config.story.prose_target_words,
        )

        self.designs = DesignService()
        self.manuscripts = ManuscriptService()
        self.knowledge = KnowledgeService()
        self.quality = QualityService()
        self.commits = StoryCommitCoordinator(self.repository, self.index_service)

        policy = GenerationPolicy(
            min_quality_score=self.config.generation.min_quality_score,
            max_repairs=self.config.generation.max_repairs,
            require_contract_pass=self.config.generation.require_contract_pass,
            require_continuity_pass=self.config.generation.require_continuity_pass,
        )
        self.generation = ChapterGenerationPipeline(
            composer=self.chapter_composer,
            context=self.writing_context,
            evaluator=CandidateEvaluator(
                contracts=self.contract_validator,
                continuity=self.continuity_auditor,
                critic=self.critic,
                policy=policy,
            ),
            editor=self.editor,
        )
        self.chapter_workflow = ChapterWorkflow(
            generation=self.generation,
            knowledge=self.knowledge_pipeline,
            manuscripts=self.manuscripts,
            quality=self.quality,
            commits=self.commits,
        )
        self.planning = StoryPlanningService(
            planner=self.planner,
            scenes=self.chapter_composer,
            context=self.writing_context,
            designs=self.designs,
            manuscripts=self.manuscripts,
            quality=self.quality,
            commits=self.commits,
        )
        self.reviewing = ChapterReviewService(
            context=self.writing_context,
            critic=self.critic,
            contracts=self.contract_validator,
            continuity=self.continuity_auditor,
            character_auditor=self.character_auditor,
            consistency=self.knowledge_system,
            quality=self.quality,
            commits=self.commits,
        )
        self.editing = ChapterEditingService(
            editor=self.editor,
            generation=self.generation,
            workflow=self.chapter_workflow,
            knowledge=self.knowledge_pipeline,
            manuscripts=self.manuscripts,
            quality=self.quality,
            commits=self.commits,
            proposals=self.agent_run_repository,
        )
        self.batch = BatchWritingService(
            planning=self.planning,
            chapters=self.chapter_workflow,
        )
        self.agent_toolbox = StoryAgentToolbox(self)
        self.agent_runtime = StoryAgentRuntime(
            self.story_orchestrator,
            self.agent_toolbox,
            self.agent_run_repository,
        )
        self.story: Story | None = None

    @property
    def state_dir(self) -> Path:
        """Directory for disposable exports; canonical state lives in SQLite."""
        return self.artifact_store.root

    @property
    def current_story(self) -> Story:
        """Return the loaded aggregate or fail before entering a use case."""
        return self._require_story()

    def start_new_story(
        self,
        premise: str,
        title: str = "Untitled Novel",
        genre: str = "novel",
        style_guide: str = "",
    ) -> Story:
        self.story = self.planning.create(premise, title, genre, style_guide)
        return self.story

    def generate_outline(self, num_chapters: int | None = None, force: bool = False) -> list:
        target = num_chapters or self.config.story.default_chapters
        self.story = self.planning.outline(self._require_story(), target, force)
        return self.story.design.outlines

    def upsert_character(self, character: Character) -> Character:
        working = self._require_story().model_copy(deep=True)
        self.designs.add_character(working, character)
        self.quality.invalidate_story_assessments(working)
        working.touch()
        self.story = self.commits.save_and_reindex(
            working,
            event_type="story_design_changed",
        ).story
        return self.story.design.characters[character.id]

    def upsert_world_setting(self, setting: WorldSetting) -> WorldSetting:
        working = self._require_story().model_copy(deep=True)
        self.designs.add_world_setting(working, setting)
        self.quality.invalidate_story_assessments(working)
        working.touch()
        self.story = self.commits.save_and_reindex(
            working,
            event_type="story_design_changed",
        ).story
        return next(item for item in self.story.design.world_settings if item.id == setting.id)

    def generate_beats(self, chapter_index: int) -> Chapter:
        result = self.planning.plan_beats(self._require_story(), chapter_index)
        self.story = result.story
        return result.chapter

    def ensure_chapter_contract(
        self,
        chapter_index: int,
        force: bool = False,
    ) -> ChapterContract:
        result = self.planning.ensure_contract(
            self._require_story(),
            chapter_index,
            force,
        )
        self.story = result.story
        return result.contract

    def update_chapter_contract(
        self,
        chapter_index: int,
        contract: ChapterContract,
    ) -> ChapterContract:
        result = self.planning.update_contract(
            self._require_story(),
            chapter_index,
            contract,
        )
        self.story = result.story
        return result.contract

    def write_chapter(self, chapter_index: int) -> Chapter:
        contract = self.ensure_chapter_contract(chapter_index)
        try:
            result = self.chapter_workflow.write(
                self._require_story(),
                chapter_index,
                contract,
                self._polish_draft,
            )
        except GenerationRejected as exc:
            if isinstance(exc.story, Story):
                self.story = exc.story
            raise
        self.story = result.story
        return result.chapter

    def request_review(self, chapter_index: int) -> ReviewReport:
        result = self.reviewing.review(self._require_story(), chapter_index)
        self.story = result.story
        return result.report

    def validate_chapter_contract(self, chapter_index: int) -> list[ConstraintCheck]:
        self.ensure_chapter_contract(chapter_index)
        return self.reviewing.validate_contract(self._require_story(), chapter_index)

    def audit_chapter_continuity(self, chapter_index: int) -> ContinuityAuditReport:
        result = self.reviewing.audit_continuity(self._require_story(), chapter_index)
        self.story = result.story
        return result.report

    def audit_character_continuity(
        self,
        character_query: str,
        start_chapter: int,
        end_chapter: int,
    ) -> CharacterContinuityReport:
        result = self.reviewing.audit_character(
            self._require_story(),
            character_query,
            start_chapter,
            end_chapter,
        )
        self.story = result.story
        return result.report

    def update_chapter_content(
        self,
        chapter_index: int,
        content: str,
        title: str | None = None,
        status: ChapterStatus | str = ChapterStatus.DRAFT,
    ) -> Chapter:
        result = self.editing.save_user_content(
            self._require_story(),
            chapter_index,
            content,
            title,
            status,
        )
        self.story = result.story
        return result.chapter

    def create_revision_proposal(
        self,
        chapter_index: int,
        instruction: str,
    ) -> RevisionProposal:
        result = self.editing.create_proposal(
            self._require_story(),
            chapter_index,
            instruction,
        )
        self.story = result.story
        return result.proposal

    def get_revision_proposal(self, proposal_id: str) -> RevisionProposal | None:
        return self.editing.get_proposal(self._require_story(), proposal_id)

    def accept_revision_proposal(self, proposal_id: str) -> Chapter:
        result = self.editing.accept_proposal(self._require_story(), proposal_id)
        self.story = result.story
        return result.chapter

    def reject_revision_proposal(self, proposal_id: str) -> RevisionProposal:
        result = self.editing.reject_proposal(self._require_story(), proposal_id)
        self.story = result.story
        return result.proposal

    def batch_write_chapters(
        self,
        start_chapter: int,
        end_chapter: int,
    ) -> BatchWriteReport:
        self.story, report = self.batch.write_range(
            self._require_story(),
            start_chapter,
            end_chapter,
            self._polish_draft,
        )
        return report

    def run_agent_goal(self, goal: str, max_steps: int = 12) -> AgentRun:
        """Let the Story Orchestrator plan and execute one bounded user goal."""
        return self.agent_runtime.start(goal, max_steps=max_steps)

    def resume_agent_run(self, run_id: str, user_input: str = "") -> AgentRun:
        return self.agent_runtime.resume(run_id, user_input=user_input)

    def get_agent_run_details(self, run_id: str) -> dict[str, object]:
        return self.agent_runtime.details(run_id)

    def list_agent_runs(self, limit: int = 50) -> list[AgentRun]:
        return self.agent_run_repository.list_runs(self._require_story().id, limit=limit)

    def finalize_chapter(self, chapter_index: int) -> Chapter:
        result = self.editing.finalize(self._require_story(), chapter_index)
        self.story = result.story
        return result.chapter

    def list_character_facts(self, chapter_index: int | None = None) -> list[CharacterFact]:
        story = self._require_story()
        if chapter_index is None:
            return list(story.knowledge.character_facts)
        return self.knowledge_system.fact_ledger.facts_at(story, chapter_index)

    def upsert_character_fact(self, fact: CharacterFact) -> CharacterFact:
        working = self._require_story().model_copy(deep=True)
        saved = self.knowledge.confirm_fact(
            working,
            fact,
            self.knowledge_system.fact_ledger,
        )
        working.touch()
        self.story = self.commits.save_and_reindex(
            working,
            event_type="confirmed_fact_changed",
        ).story
        return saved

    def delete_character_fact(self, fact_id: str) -> bool:
        working = self._require_story().model_copy(deep=True)
        deleted = self.knowledge.remove_confirmed_fact(
            working,
            fact_id,
            self.knowledge_system.fact_ledger,
        )
        if deleted:
            working.touch()
            self.story = self.commits.save_and_reindex(
                working,
                event_type="confirmed_fact_changed",
            ).story
        return deleted

    def save_state(self) -> Path:
        story = self._require_story().model_copy(deep=True)
        story.touch()
        self.story = self.commits.save(story).story
        return self.repository.database_path

    def load_state(self, story_id: str | UUID) -> Story:
        self.story = self.repository.load(story_id)
        return self.story

    def export_markdown(self, output_path: str | Path | None = None) -> Path:
        return self.export_service.export_markdown(self._require_story(), output_path)

    def export_docx(self, output_path: str | Path | None = None) -> Path:
        return self.export_service.export_docx(self._require_story(), output_path)

    def delete_story_data(self, story_id: str | UUID) -> dict[str, object]:
        result = self.storage_service.delete_story(story_id)
        if self.story is not None and str(self.story.id) == str(story_id):
            self.story = None
        return result

    def rebuild_derived_indexes(
        self,
        story_id: str | UUID | None = None,
    ) -> dict[str, int | str]:
        target = story_id or self._require_story().id
        return self.storage_service.rebuild_indexes(target)

    def storage_status(self, story_id: str | UUID | None = None) -> dict[str, object]:
        target = story_id or self._require_story().id
        return self.storage_service.status(target)

    def close(self) -> None:
        """Release infrastructure resources owned by this facade instance."""
        close_text = getattr(self.text_store, "close", None)
        if callable(close_text):
            close_text()
        self.repository.close()
        self.agent_run_repository.close()

    def _polish_draft(self, story: Story, chapter_index: int, content: str) -> str:
        if not self.config.story.auto_polish_drafts:
            return content
        outline = story.get_outline(chapter_index)
        instructions = (
            f"Target length: about {self.config.story.prose_target_words} Chinese characters. "
            f"Chapter title: {outline.title}. Conflict: {outline.conflict}. "
            "Improve scene detail, character action, subtext, and paragraph rhythm. "
            "Preserve every established fact and the intended ending. "
            f"Style guide: {story.style_guide or 'clear, restrained, vivid prose'}."
        )
        polished = self.editor.polish_prose(content, instructions).strip()
        return polished or content

    def _require_story(self) -> Story:
        if self.story is None:
            raise RuntimeError("No story is loaded.")
        return self.story


__all__ = ["NovelForgeEngine"]
