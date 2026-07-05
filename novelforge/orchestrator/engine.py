"""Finite-state workflow engine for NovelForge."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from novelforge.agents import CriticAgent, EditorAgent, PlannerAgent, WriterAgent
from novelforge.context.assembler import ContextAssembler
from novelforge.core.config import AppConfig, load_config
from novelforge.core.exceptions import PersistenceError, WorkflowError
from novelforge.core.models import AutoRevisionReport, Chapter, ReviewReport, Story
from novelforge.llm import build_llm_client
from novelforge.longform.manager import LongformManager
from novelforge.memory.graph_store import NetworkXGraphStore
from novelforge.memory.text_store import SQLiteFTSStore
from novelforge.memory.vector_store import ChromaVectorStore
from novelforge.orchestrator.auto_revisor import AutoRevisor, AutoRevisorConfig
from novelforge.orchestrator.bus import EventBus
from novelforge.storage.repository import StoryRepository


class WorkflowState(StrEnum):
    PLANNING = "planning"
    OUTLINE_GENERATED = "outline_generated"
    CHAPTER_BEATS_READY = "chapter_beats_ready"
    CHAPTER_DRAFT = "chapter_draft"
    REVIEWING = "reviewing"
    REVISING = "revising"
    CHAPTER_FINALIZED = "chapter_finalized"
    COMPLETED = "completed"


class NovelForgeEngine:
    def __init__(self, config: AppConfig | None = None, bus: EventBus | None = None):
        self.config = config or load_config()
        self.bus = bus or EventBus()
        self.llm = build_llm_client(self.config.llm)
        self.vector_store = ChromaVectorStore(self.config.memory.persist_directory)
        self.graph_store = NetworkXGraphStore(self.config.memory.graph_directory)
        self.text_store = SQLiteFTSStore(self.config.memory.sqlite_path)
        self.longform_manager = LongformManager(self.llm)
        self.context_assembler = ContextAssembler(
            self.vector_store,
            self.graph_store,
            self.text_store,
            self.config.story.max_context_tokens,
            self.longform_manager,
        )
        self.planner = PlannerAgent(self.llm)
        self.writer = WriterAgent(self.llm)
        self.critic = CriticAgent(self.llm)
        self.editor = EditorAgent(self.llm)
        self.story: Story | None = None
        self.last_review: dict[int, ReviewReport] = {}
        self.current_auto_revisor: AutoRevisor | None = None
        self.auto_status: str = "idle"
        self.repository = StoryRepository(Path(self.config.memory.sqlite_path).parent)

    @property
    def state_dir(self) -> Path:
        path = Path("./novelforge/storage/story_state")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def start_new_story(
        self,
        premise: str,
        title: str = "Untitled Novel",
        genre: str = "novel",
        style_guide: str = "",
    ) -> Story:
        self.story = Story(title=title, premise=premise, genre=genre, style_guide=style_guide)
        self.bus.emit("story_started", {"story_id": str(self.story.id)})
        self.save_state()
        return self.story

    def generate_outline(self, num_chapters: int | None = None) -> list:
        story = self._require_story()
        story.outlines = self.planner.generate_outline(
            story.premise,
            num_chapters or self.config.story.default_chapters,
        )
        story.status = WorkflowState.OUTLINE_GENERATED.value
        story.touch()
        self.save_state()
        self.bus.emit("outline_generated", {"story_id": str(story.id), "chapters": len(story.outlines)})
        return story.outlines

    def generate_beats(self, chapter_index: int) -> Chapter:
        story = self._require_story()
        outline = story.get_outline(chapter_index)
        context = self.context_assembler.assemble_writing_context(chapter_index, story)
        beats = self.planner.generate_beats(outline, context)
        chapter = story.chapters.get(chapter_index) or Chapter(index=chapter_index, title=outline.title)
        chapter.beats = beats
        story.chapters[chapter_index] = chapter
        story.current_chapter = chapter_index
        story.status = WorkflowState.CHAPTER_BEATS_READY.value
        story.touch()
        self.save_state()
        self.bus.emit("beats_generated", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def write_chapter(self, chapter_index: int) -> Chapter:
        story = self._require_story()
        outline = story.get_outline(chapter_index)
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.beats:
            chapter = self.generate_beats(chapter_index)
        context = self.context_assembler.assemble_writing_context(chapter_index, story)
        content = self.writer.write_chapter(chapter_index, outline, chapter.beats, context, story.style_guide)
        chapter.update_content(content, status="draft", summary=outline.summary)
        story.chapters[chapter_index] = chapter
        story.current_chapter = chapter_index
        story.status = WorkflowState.CHAPTER_DRAFT.value
        self._index_chapter(story, chapter)
        self.longform_manager.process_new_chapter(story, chapter_index, chapter.content)
        story.touch()
        self.save_state()
        self.bus.emit("chapter_written", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def request_review(self, chapter_index: int) -> ReviewReport:
        story = self._require_story()
        outline = story.get_outline(chapter_index)
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no draft to review.")
        memories = self.vector_store.query("plot_summaries", outline.summary, k=5)
        longform_context = self.longform_manager.get_enhanced_context(chapter_index, story)
        report = self.critic.review_chapter(
            chapter.content,
            outline,
            list(story.characters.values()),
            memories,
            longform_context,
        )
        checks = self.longform_manager.review_chapter_consistency(story, chapter_index, chapter.content)
        report.logic_issues.extend(checks["foreshadowing_issues"])
        report.pacing_issues.extend(checks["pacing_issues"])
        report.character_issues.extend(checks["character_state_issues"])
        self.last_review[chapter_index] = report
        chapter.status = "reviewed"
        story.status = WorkflowState.REVIEWING.value
        story.touch()
        self.save_state()
        self.bus.emit("chapter_reviewed", {"story_id": str(story.id), "chapter": chapter_index})
        return report

    def apply_revision(self, chapter_index: int, revised_content: str | None = None) -> Chapter:
        story = self._require_story()
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no content to revise.")
        report = self.last_review.get(chapter_index) or self.request_review(chapter_index)
        content = revised_content or self.editor.revise_chapter(chapter.content, report, story.style_guide)
        chapter.update_content(content, status="revised", summary=chapter.summary)
        story.status = WorkflowState.REVISING.value
        story.touch()
        self._index_chapter(story, chapter)
        self.longform_manager.process_new_chapter(story, chapter_index, chapter.content)
        self.save_state()
        self.bus.emit("chapter_revised", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def auto_write_chapter(self, chapter_index: int) -> AutoRevisionReport:
        story = self._require_story()
        outline = story.get_outline(chapter_index)
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.beats:
            chapter = self.generate_beats(chapter_index)

        config = AutoRevisorConfig(
            max_rounds=self.config.auto_revisor.max_rounds,
            pass_threshold=self.config.auto_revisor.pass_threshold,
            quality_weights=self.config.auto_revisor.quality_weights,
        )
        self.current_auto_revisor = AutoRevisor(
            story=story,
            writer=self.writer,
            critic=self.critic,
            editor=self.editor,
            assembler=self.context_assembler,
            config=config,
        )
        self.auto_status = "running"
        self.bus.emit("auto_revision_started", {"story_id": str(story.id), "chapter": chapter_index})
        result = self.current_auto_revisor.run(chapter_index)

        chapter = story.chapters.get(chapter_index) or Chapter(index=chapter_index, title=outline.title)
        chapter.update_content(
            result.final_content,
            status="revised" if result.passed else "reviewed",
            summary=chapter.summary or outline.summary,
        )
        story.chapters[chapter_index] = chapter
        story.current_chapter = chapter_index
        story.auto_revision_reports[chapter_index] = result
        story.status = WorkflowState.CHAPTER_FINALIZED.value if result.passed else WorkflowState.REVISING.value
        self._index_chapter(story, chapter)
        self.longform_manager.process_new_chapter(story, chapter_index, chapter.content)
        story.touch()
        self.save_state()
        self.auto_status = self.current_auto_revisor.status
        self.bus.emit(
            "auto_revision_finished",
            {
                "story_id": str(story.id),
                "chapter": chapter_index,
                "passed": result.passed,
                "final_score": result.final_score,
            },
        )
        return result

    def get_auto_status(self) -> dict[str, object]:
        if self.current_auto_revisor is None:
            return {"status": self.auto_status, "round": 0, "stop_requested": False}
        return {
            "status": self.current_auto_revisor.status,
            "round": self.current_auto_revisor.current_round,
            "stop_requested": self.current_auto_revisor.stop_requested,
        }

    def stop_auto_revision(self) -> bool:
        if self.current_auto_revisor is None:
            return False
        self.current_auto_revisor.request_stop()
        self.auto_status = "stop_requested"
        return True

    def finalize_chapter(self, chapter_index: int) -> Chapter:
        story = self._require_story()
        chapter = story.chapters[chapter_index]
        chapter.status = "finalized"
        story.status = WorkflowState.CHAPTER_FINALIZED.value
        if chapter_index >= len(story.outlines):
            story.status = WorkflowState.COMPLETED.value
        if chapter.content:
            self.longform_manager.process_new_chapter(story, chapter_index, chapter.content)
        story.touch()
        self.save_state()
        self.bus.emit("chapter_finalized", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def advance_to_next_chapter(self) -> Chapter:
        story = self._require_story()
        next_index = max(story.current_chapter + 1, 1)
        if next_index > len(story.outlines):
            story.status = WorkflowState.COMPLETED.value
            self.save_state()
            raise WorkflowError("Story is completed; no next chapter exists.")
        return self.generate_beats(next_index)

    def save_state(self) -> Path:
        story = self._require_story()
        try:
            return self.repository.save(story)
        except Exception as exc:
            raise PersistenceError(f"Could not save story state: {exc}") from exc

    def load_state(self, story_id: str | UUID) -> Story:
        if not self.repository.exists(story_id):
            raise PersistenceError(f"Story state not found: {self.repository.story_path(story_id)}")
        try:
            self.story = self.repository.load(story_id)
            return self.story
        except Exception as exc:
            raise PersistenceError(f"Could not load story state: {exc}") from exc

    def export_markdown(self, output_path: str | Path | None = None) -> Path:
        story = self._require_story()
        output = Path(output_path or self.state_dir / f"{story.title}.md")
        lines = [f"# {story.title}", "", f"> {story.premise}", ""]
        for index in sorted(story.chapters):
            chapter = story.chapters[index]
            lines.extend([f"## {chapter.title}", "", chapter.content, ""])
        output.write_text("\n".join(lines), encoding="utf-8")
        return output

    def export_auto_revision_report(self, chapter_index: int, output_path: str | Path | None = None) -> Path:
        story = self._require_story()
        report = story.auto_revision_reports.get(chapter_index)
        if report is None:
            raise WorkflowError(f"No auto-revision report for chapter {chapter_index}.")
        return self.repository.export_auto_revision_report(story, report, output_path)

    def _index_chapter(self, story: Story, chapter: Chapter) -> None:
        doc_id = f"{story.id}:chapter:{chapter.index}:v{chapter.version}"
        self.text_store.index_document(doc_id, chapter.content)
        self.vector_store.add(
            "plot_summaries",
            [chapter.summary or chapter.content[:500]],
            [{"type": "chapter_summary", "chapter": chapter.index, "version": chapter.version}],
            [doc_id],
        )

    def _require_story(self) -> Story:
        if self.story is None:
            raise WorkflowError("No active story. Start or load a story first.")
        return self.story
