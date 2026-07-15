"""Atomic chapter-to-knowledge processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novelforge.domain import (
    Chapter,
    ChapterKnowledgeDelta,
    KnowledgeSource,
    Story,
    content_digest,
)
from novelforge.longform.knowledge_system import StoryKnowledgeSystem


@dataclass(frozen=True)
class ChapterKnowledgeResult:
    """Committed knowledge delta plus non-canonical extraction metadata."""

    delta: ChapterKnowledgeDelta
    extraction: Any
    pacing: dict[str, Any]
    pacing_warning: str


class ChapterKnowledgePipeline:
    """Convert approved prose into canonical knowledge in one commit.

    Existing extractors are allowed to mutate only a deep working copy. The
    official Story is updated after every stage succeeds, so partial knowledge
    cannot leak from a failed extraction.
    """

    def __init__(self, processor: StoryKnowledgeSystem) -> None:
        self.processor = processor

    def process(self, story: Story, chapter: Chapter) -> ChapterKnowledgeResult:
        """Extract, validate, and atomically commit one chapter's knowledge."""
        official = story.manuscript.chapters.get(chapter.index)
        if (
            official is None
            or official.version != chapter.version
            or official.content != chapter.content
        ):
            raise ValueError(
                "Knowledge can only be derived from the currently committed chapter version."
            )
        working = story.model_copy(deep=True)
        self._remove_chapter_projection(working, chapter.index)
        raw = self.processor.process_new_chapter(working, chapter.index, chapter.content)
        summary = working.knowledge.chapter_summaries[chapter.index]
        source = KnowledgeSource(
            chapter_index=chapter.index,
            manuscript_version=chapter.version,
            content_digest=content_digest(chapter.content),
        )
        delta = ChapterKnowledgeDelta(
            chapter_index=chapter.index,
            source=source,
            summary=summary,
            character_observations=[
                item
                for item in working.knowledge.character_observations
                if item.source_chapter == chapter.index
            ],
            world_facts=[
                item
                for item in working.knowledge.world_facts
                if item.source_chapter == chapter.index
            ],
            relationships=[
                item
                for item in working.knowledge.relationships
                if item.source_chapter == chapter.index
            ],
            character_facts=[
                fact
                for fact in working.knowledge.character_facts
                if fact.source_chapter == chapter.index
            ],
            character_states=[
                state
                for history in working.knowledge.character_states.values()
                for state in history
                if state.chapter == chapter.index
            ],
            timeline=[
                event for event in working.knowledge.timeline if event.chapter == chapter.index
            ],
            foreshadowings=[
                item
                for item in working.knowledge.foreshadowings
                if item.created_chapter == chapter.index or item.resolved_chapter == chapter.index
            ],
            retrieval_notes=[
                note for note in working.knowledge.retrieval_notes if note.chapter == chapter.index
            ],
            continuity_constraints=list(
                working.knowledge.chapter_constraints.get(chapter.index, [])
            ),
        )

        working.knowledge.sources[chapter.index] = source
        story.knowledge = working.knowledge
        return ChapterKnowledgeResult(
            delta=delta,
            extraction=raw.get("extraction"),
            pacing=raw.get("pacing", {}),
            pacing_warning=str(raw.get("pacing_warning", "")),
        )

    def _remove_chapter_projection(self, story: Story, chapter_index: int) -> None:
        """Give a rewritten chapter replacement semantics instead of append semantics."""
        knowledge = story.knowledge
        knowledge.sources.pop(chapter_index, None)
        knowledge.character_observations = [
            item
            for item in knowledge.character_observations
            if item.source_chapter != chapter_index
        ]
        knowledge.world_facts = [
            item for item in knowledge.world_facts if item.source_chapter != chapter_index
        ]
        knowledge.relationships = [
            item for item in knowledge.relationships if item.source_chapter != chapter_index
        ]
        knowledge.character_facts = [
            fact for fact in knowledge.character_facts if fact.source_chapter != chapter_index
        ]
        knowledge.character_states = {
            character_id: [state for state in states if state.chapter != chapter_index]
            for character_id, states in knowledge.character_states.items()
            if any(state.chapter != chapter_index for state in states)
        }
        knowledge.timeline = [
            event for event in knowledge.timeline if event.chapter != chapter_index
        ]
        remaining_event_ids = {event.id for event in knowledge.timeline}
        for event in knowledge.timeline:
            event.causes = [item for item in event.causes if item in remaining_event_ids]
            event.effects = [item for item in event.effects if item in remaining_event_ids]
        knowledge.foreshadowings = [
            item for item in knowledge.foreshadowings if item.created_chapter != chapter_index
        ]
        for item in knowledge.foreshadowings:
            if item.resolved_chapter == chapter_index:
                item.status = "pending"
                item.resolved_chapter = None
        knowledge.chapter_summaries.pop(chapter_index, None)
        knowledge.chapter_constraints.pop(chapter_index, None)
        knowledge.retrieval_notes = [
            note for note in knowledge.retrieval_notes if note.chapter != chapter_index
        ]
