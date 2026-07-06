"""Finite-state workflow engine for NovelForge."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Callable
from uuid import UUID

from novelforge.agents import (
    ContinuityAuditorAgent,
    CriticAgent,
    EditorAgent,
    PlannerAgent,
    SupervisorAgent,
    WriterAgent,
)
from novelforge.context.assembler import ContextAssembler
from novelforge.core.config import AppConfig, load_config
from novelforge.core.exceptions import PersistenceError, WorkflowError
from novelforge.core.models import (
    AutoRevisionReport,
    AutonomousRunReport,
    BatchChapterResult,
    BatchWriteReport,
    Chapter,
    ContinuityAuditReport,
    ReviewReport,
    Story,
    utc_now,
)
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
        self.supervisor = SupervisorAgent(self.llm)
        self.writer = WriterAgent(self.llm)
        self.critic = CriticAgent(self.llm)
        self.editor = EditorAgent(self.llm)
        self.continuity_auditor = ContinuityAuditorAgent(self.llm)
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
        content = self._polish_draft_if_enabled(story, chapter_index, content)
        chapter.update_content(content, status="draft", summary=outline.summary)
        story.chapters[chapter_index] = chapter
        story.current_chapter = chapter_index
        story.status = WorkflowState.CHAPTER_DRAFT.value
        self._process_chapter_memory(story, chapter)
        story.touch()
        self.save_state()
        self.bus.emit("chapter_written", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def _polish_draft_if_enabled(self, story: Story, chapter_index: int, content: str) -> str:
        if not self.config.story.auto_polish_drafts:
            return content
        outline = story.get_outline(chapter_index)
        instructions = (
            f"目标字数约 {self.config.story.prose_target_words} 字；"
            "把草稿改成更有小说质感的完整正文。"
            "保留章节大纲、节拍和长篇记忆中的事实，不改变结局走向。"
            "加强场景细节、人物动作、心理波动、对话潜台词和段落节奏。"
            f"本章标题: {outline.title}；核心冲突: {outline.conflict}；"
            f"文风: {story.style_guide or '清晰克制，有画面感，避免流水账。'}"
        )
        polished = self.editor.polish_prose(content, instructions)
        return polished or content

    def request_review(self, chapter_index: int) -> ReviewReport:
        story = self._require_story()
        outline = story.get_outline(chapter_index)
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no draft to review.")
        memories = self.vector_store.query("plot_summaries", outline.summary, k=5)
        memories.extend(self.vector_store.query("memory_cards", outline.summary, k=5))
        longform_context = self.longform_manager.get_enhanced_context(chapter_index, story, query=outline.summary)
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

    def audit_chapter_continuity(self, chapter_index: int) -> ContinuityAuditReport:
        story = self._require_story()
        chapter = story.chapters.get(chapter_index)
        if chapter is None or not chapter.content:
            raise WorkflowError(f"Chapter {chapter_index} has no content to audit.")
        outline = None
        try:
            outline = story.get_outline(chapter_index)
        except KeyError:
            outline = None
        query = outline.summary if outline else chapter.summary or chapter.title
        longform_context = self.longform_manager.get_enhanced_context(chapter_index, story, query=query)
        report = self.continuity_auditor.audit_chapter(story, chapter_index, chapter.content, longform_context)
        story.continuity_reports[chapter_index] = report
        story.touch()
        self.save_state()
        self.bus.emit(
            "chapter_continuity_audited",
            {
                "story_id": str(story.id),
                "chapter": chapter_index,
                "risk_score": report.risk_score,
                "passed": report.passed,
            },
        )
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
        self._process_chapter_memory(story, chapter)
        self.save_state()
        self.bus.emit("chapter_revised", {"story_id": str(story.id), "chapter": chapter_index})
        return chapter

    def update_chapter_content(
        self,
        chapter_index: int,
        content: str,
        title: str | None = None,
        status: str = "draft",
    ) -> Chapter:
        story = self._require_story()
        outline = None
        try:
            outline = story.get_outline(chapter_index)
        except KeyError:
            outline = None
        chapter = story.chapters.get(chapter_index) or Chapter(
            index=chapter_index,
            title=title or (outline.title if outline else f"Chapter {chapter_index}"),
        )
        if title:
            chapter.title = title
        chapter.update_content(content, status=status, summary=chapter.summary or (outline.summary if outline else ""))
        story.chapters[chapter_index] = chapter
        story.current_chapter = chapter_index
        story.status = WorkflowState.CHAPTER_DRAFT.value if status == "draft" else story.status
        self._process_chapter_memory(story, chapter)
        story.touch()
        self.save_state()
        self.bus.emit("chapter_updated", {"story_id": str(story.id), "chapter": chapter_index})
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
        self._process_chapter_memory(story, chapter)
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

    def batch_write_chapters(
        self,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> BatchWriteReport:
        if start_chapter < 1 or end_chapter < start_chapter:
            raise WorkflowError("Invalid chapter range.")
        story = self._require_story()
        total = end_chapter - start_chapter + 1

        def emit_progress(
            message: str,
            chapter_index: int | None = None,
            stage: str = "working",
            progress_current: int | None = None,
        ) -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "message": message,
                    "chapter_index": chapter_index,
                    "stage": stage,
                    "progress_current": progress_current if progress_current is not None else 0,
                    "progress_total": total,
                    "status": "running_batch",
                }
            )

        if len(story.outlines) < end_chapter:
            emit_progress(
                f"Generating outline up to chapter {end_chapter}",
                stage="outline",
                progress_current=0,
            )
        self._ensure_outlines(end_chapter)
        report = BatchWriteReport(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            use_auto_revision=use_auto_revision,
        )
        for chapter_index in range(start_chapter, end_chapter + 1):
            try:
                chapter = story.chapters.get(chapter_index)
                if chapter is None or not chapter.beats:
                    emit_progress(
                        f"Chapter {chapter_index}: generating beats",
                        chapter_index=chapter_index,
                        stage="beats",
                        progress_current=report.completed,
                    )
                    self.generate_beats(chapter_index)
                if use_auto_revision:
                    emit_progress(
                        f"Chapter {chapter_index}: writing, reviewing, and revising",
                        chapter_index=chapter_index,
                        stage="auto_revision",
                        progress_current=report.completed,
                    )
                    auto_report = self.auto_write_chapter(chapter_index)
                    chapter = story.chapters[chapter_index]
                    report.results.append(
                        BatchChapterResult(
                            chapter_index=chapter_index,
                            status="passed" if auto_report.passed else "reviewed",
                            title=chapter.title,
                            word_count=len(chapter.content),
                            auto_revision_score=auto_report.final_score,
                            message=f"{len(auto_report.rounds)} auto-revision rounds",
                        )
                    )
                else:
                    emit_progress(
                        f"Chapter {chapter_index}: writing draft",
                        chapter_index=chapter_index,
                        stage="draft",
                        progress_current=report.completed,
                    )
                    chapter = self.write_chapter(chapter_index)
                    report.results.append(
                        BatchChapterResult(
                            chapter_index=chapter_index,
                            status=chapter.status,
                            title=chapter.title,
                            word_count=len(chapter.content),
                            message="draft generated",
                        )
                    )
                report.completed += 1
                emit_progress(
                    f"Chapter {chapter_index}: completed",
                    chapter_index=chapter_index,
                    stage="completed",
                    progress_current=report.completed,
                )
            except Exception as exc:
                report.failed += 1
                emit_progress(
                    f"Chapter {chapter_index}: failed - {exc}",
                    chapter_index=chapter_index,
                    stage="failed",
                    progress_current=report.completed,
                )
                report.results.append(
                    BatchChapterResult(
                        chapter_index=chapter_index,
                        status="failed",
                        message=str(exc),
                    )
                )
        story.batch_reports.append(report)
        story.touch()
        self.save_state()
        self.bus.emit(
            "batch_write_finished",
            {
                "story_id": str(story.id),
                "start": start_chapter,
                "end": end_chapter,
                "completed": report.completed,
                "failed": report.failed,
            },
        )
        return report

    def agentic_writing_run(
        self,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> AutonomousRunReport:
        if start_chapter < 1 or end_chapter < start_chapter:
            raise WorkflowError("Invalid chapter range.")
        story = self._require_story()
        run = self.supervisor.plan_writing_run(
            story=story,
            objective=objective,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            use_auto_revision=use_auto_revision,
        )
        story.agent_runs.append(run)
        run.status = "running"
        run.updated_at = utc_now()
        story.touch()
        self.save_state()
        self._emit_agent_progress(
            run,
            "SupervisorAgent",
            "plan_run",
            f"Planned with {run.planning_strategy}: {run.planning_notes or run.summary}",
            progress_callback,
        )

        for task in run.tasks:
            task.status = "running"
            task.started_at = utc_now()
            run.updated_at = utc_now()
            story.touch()
            self.save_state()
            self._emit_agent_progress(
                run,
                task.agent,
                task.action,
                task.reason,
                progress_callback,
                chapter_index=task.chapter_index,
                task_id=task.id,
            )
            try:
                task.output_summary = self._execute_agent_task(task, end_chapter)
                task.status = "completed"
                task.completed_at = utc_now()
                run.completed_tasks += 1
                self._emit_agent_progress(
                    run,
                    task.agent,
                    task.action,
                    task.output_summary,
                    progress_callback,
                    chapter_index=task.chapter_index,
                    task_id=task.id,
                )
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                task.completed_at = utc_now()
                run.failed_tasks += 1
                self._emit_agent_progress(
                    run,
                    task.agent,
                    task.action,
                    f"Failed: {exc}",
                    progress_callback,
                    chapter_index=task.chapter_index,
                    task_id=task.id,
                )
                break
            finally:
                run.updated_at = utc_now()
                story.touch()
                self.save_state()

        run.status = "failed" if run.failed_tasks else "completed"
        run.summary = (
            f"Agentic run {run.status}: {run.completed_tasks}/{len(run.tasks)} tasks completed, "
            f"{run.failed_tasks} failed."
        )
        run.updated_at = utc_now()
        story.touch()
        self.save_state()
        self.bus.emit(
            "agentic_run_finished",
            {
                "story_id": str(story.id),
                "run_id": run.id,
                "status": run.status,
                "completed_tasks": run.completed_tasks,
                "failed_tasks": run.failed_tasks,
            },
        )
        return run

    def _execute_agent_task(self, task, end_chapter: int) -> str:
        story = self._require_story()
        if task.action == "ensure_outline":
            before = len(story.outlines)
            if before < end_chapter:
                self._ensure_outlines(end_chapter)
                return f"Generated outlines through chapter {end_chapter}."
            return f"Outline already covers {before} chapters."
        if task.chapter_index is None:
            raise WorkflowError(f"Task {task.id} requires a chapter index.")
        if task.action == "generate_beats":
            chapter = self.generate_beats(task.chapter_index)
            return f"Generated {len(chapter.beats)} scene beats."
        if task.action == "write_chapter":
            chapter = self.write_chapter(task.chapter_index)
            return f"Wrote draft with {len(chapter.content)} characters."
        if task.action == "auto_write_chapter":
            report = self.auto_write_chapter(task.chapter_index)
            return f"Auto-revision finished with score {report.final_score:.2f}; passed={report.passed}."
        if task.action == "audit_chapter_continuity":
            report = self.audit_chapter_continuity(task.chapter_index)
            return f"Continuity risk {report.risk_score:.1f}; passed={report.passed}."
        if task.action == "memory_checkpoint":
            chapter = story.chapters.get(task.chapter_index)
            if chapter is None or not chapter.content:
                raise WorkflowError(f"Chapter {task.chapter_index} has no content to index.")
            self._process_chapter_memory(story, chapter)
            return (
                f"Memory updated: {len(story.memory_cards)} cards, "
                f"{len(story.chapter_summaries)} chapter summaries."
            )
        raise WorkflowError(f"Unknown agent task action: {task.action}")

    def _emit_agent_progress(
        self,
        run: AutonomousRunReport,
        agent: str,
        action: str,
        message: str,
        progress_callback: Callable[[dict[str, object]], None] | None,
        chapter_index: int | None = None,
        task_id: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "status": "running_agentic" if run.status == "running" else run.status,
                "run_id": run.id,
                "task_id": task_id,
                "agent": agent,
                "action": action,
                "message": message,
                "chapter_index": chapter_index,
                "stage": action,
                "progress_current": run.completed_tasks,
                "progress_total": len(run.tasks),
                "planning_strategy": run.planning_strategy,
            }
        )

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
            self._process_chapter_memory(story, chapter)
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

    def _ensure_outlines(self, end_chapter: int) -> None:
        story = self._require_story()
        if len(story.outlines) >= end_chapter:
            return
        story.outlines = self.planner.generate_outline(story.premise, end_chapter)
        story.status = WorkflowState.OUTLINE_GENERATED.value
        story.touch()
        self.save_state()

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

    def delete_story_data(self, story_id: str | UUID) -> dict[str, object]:
        story_id_str = str(story_id)
        result = {
            "story_id": story_id_str,
            "story_file": self.repository.delete(story_id_str),
            "vector_items": self.vector_store.delete_story(story_id_str),
            "fts_items": self.text_store.delete_story(story_id_str),
            "graph_nodes": self.graph_store.delete_story(story_id_str),
        }
        if self.story and str(self.story.id) == story_id_str:
            self.story = None
        return result

    def _index_chapter(self, story: Story, chapter: Chapter) -> None:
        doc_id = f"{story.id}:chapter:{chapter.index}:v{chapter.version}"
        self.text_store.index_document(doc_id, chapter.content)
        self.vector_store.add(
            "plot_summaries",
            [chapter.summary or chapter.content[:500]],
            [{"story_id": str(story.id), "type": "chapter_summary", "chapter": chapter.index, "version": chapter.version}],
            [doc_id],
        )

    def _process_chapter_memory(self, story: Story, chapter: Chapter) -> None:
        self._index_chapter(story, chapter)
        result = self.longform_manager.process_new_chapter(story, chapter.index, chapter.content)
        extraction = result.get("extraction") if isinstance(result, dict) else None
        if extraction is not None:
            self._index_extracted_memory(story, extraction)
        memory = result.get("memory", {}) if isinstance(result, dict) else {}
        cards = memory.get("memory_cards", []) if isinstance(memory, dict) else []
        if not cards:
            self._audit_processed_chapter(story, chapter)
            return
        self.vector_store.add(
            "memory_cards",
            [card.content for card in cards],
            [
                {
                    "story_id": str(story.id),
                    "type": card.type,
                    "chapter": card.chapter,
                    "importance": card.importance,
                    "entities": ",".join(card.entities),
                    "tags": ",".join(card.tags),
                }
                for card in cards
            ],
            [card.id if card.id.startswith(f"{story.id}:") else f"{story.id}:memory_card:{card.id}" for card in cards],
        )
        self._audit_processed_chapter(story, chapter)

    def _audit_processed_chapter(self, story: Story, chapter: Chapter) -> None:
        outline = None
        try:
            outline = story.get_outline(chapter.index)
        except KeyError:
            outline = None
        query = outline.summary if outline else chapter.summary or chapter.title
        longform_context = self.longform_manager.get_enhanced_context(chapter.index, story, query=query)
        report = self.continuity_auditor.audit_chapter(story, chapter.index, chapter.content, longform_context)
        story.continuity_reports[chapter.index] = report

    def _index_extracted_memory(self, story: Story, extraction) -> None:
        characters = getattr(extraction, "characters", [])
        if characters:
            self.vector_store.add(
                "characters",
                [
                    " ".join(
                        part
                        for part in [
                            character.name,
                            str(character.age),
                            character.appearance,
                            character.personality,
                            character.motivation,
                            character.weakness,
                            character.arc,
                        ]
                        if part
                    )
                    for character in characters
                ],
                [{"story_id": str(story.id), "type": "character", "character_id": character.id} for character in characters],
                [f"{story.id}:character:{character.id}" for character in characters],
            )
            for character in characters:
                attrs = character.model_dump()
                attrs["story_id"] = str(story.id)
                self.graph_store.add_node(f"{story.id}:character:{character.id}", attrs)

        world_settings = getattr(extraction, "world_settings", [])
        if world_settings:
            self.vector_store.add(
                "world",
                [setting.content for setting in world_settings],
                [{"story_id": str(story.id), "type": "world", "category": setting.category, **setting.metadata} for setting in world_settings],
                [f"{story.id}:world:{setting.id}" for setting in world_settings],
            )

        for relation in getattr(extraction, "relationships", []):
            self.graph_store.add_edge(
                f"{story.id}:character:{relation.source}",
                f"{story.id}:character:{relation.target}",
                relation.relation,
            )

    def _require_story(self) -> Story:
        if self.story is None:
            raise WorkflowError("No active story. Start or load a story first.")
        return self.story
