"""Story aggregate root and lifecycle invariants."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from novelforge.domain.common import DomainModel, content_digest, utc_now
from novelforge.domain.design import ChapterOutline, StoryDesign
from novelforge.domain.knowledge import StoryKnowledge
from novelforge.domain.manuscript import Chapter, Manuscript
from novelforge.domain.quality import StoryQuality
from novelforge.domain.runs import StoryRuns


class StoryStatus(StrEnum):
    PLANNING = "planning"
    OUTLINED = "outline_generated"
    BEATS_READY = "chapter_beats_ready"
    DRAFTING = "chapter_draft"
    REVIEWING = "reviewing"
    REVISING = "revising"
    FINALIZED = "chapter_finalized"
    COMPLETED = "completed"


class Story(DomainModel):
    """The only canonical aggregate persisted by the repository."""

    id: UUID = Field(default_factory=uuid4)
    title: str
    premise: str
    genre: str = "novel"
    style_guide: str = ""
    design: StoryDesign = Field(default_factory=StoryDesign)
    manuscript: Manuscript = Field(default_factory=Manuscript)
    knowledge: StoryKnowledge = Field(default_factory=StoryKnowledge)
    quality: StoryQuality = Field(default_factory=StoryQuality)
    runs: StoryRuns = Field(default_factory=StoryRuns)
    current_chapter: int = Field(default=0, ge=0)
    status: StoryStatus = StoryStatus.PLANNING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def get_outline(self, chapter_index: int) -> ChapterOutline:
        for outline in self.design.outlines:
            if outline.chapter_index == chapter_index:
                return outline
        raise KeyError(f"Chapter outline {chapter_index} does not exist.")

    def get_chapter(self, chapter_index: int) -> Chapter | None:
        return self.manuscript.chapters.get(chapter_index)

    def require_chapter(self, chapter_index: int) -> Chapter:
        chapter = self.get_chapter(chapter_index)
        if chapter is None:
            raise KeyError(f"Chapter {chapter_index} does not exist.")
        return chapter

    def touch(self) -> None:
        self.updated_at = utc_now()

    def assert_consistent(self) -> None:
        """Reject aggregate snapshots with stale or untraceable knowledge."""
        outline_indexes = [item.chapter_index for item in self.design.outlines]
        if len(outline_indexes) != len(set(outline_indexes)):
            raise ValueError("Chapter outline indexes must be unique.")
        for index, chapter in self.manuscript.chapters.items():
            if index != chapter.index:
                raise ValueError(f"Manuscript key {index} does not match chapter index.")
            if not chapter.content.strip():
                continue
            source = self.knowledge.sources.get(index)
            if source is None:
                raise ValueError(f"Chapter {index} has prose but no knowledge provenance.")
            if source.manuscript_version != chapter.version:
                raise ValueError(f"Chapter {index} knowledge is based on a stale version.")
            if source.content_digest != content_digest(chapter.content):
                raise ValueError(f"Chapter {index} knowledge digest does not match its prose.")
        for index in self.knowledge.sources:
            chapter = self.manuscript.chapters.get(index)
            if chapter is None or not chapter.content.strip():
                raise ValueError(f"Knowledge source {index} has no committed prose.")
        source_indexes = set(self.knowledge.sources)
        referenced_indexes = {
            *(item.source_chapter for item in self.knowledge.character_observations),
            *(item.source_chapter for item in self.knowledge.world_facts),
            *(item.source_chapter for item in self.knowledge.relationships),
            *(
                item.source_chapter
                for item in self.knowledge.character_facts
                if item.source_chapter is not None
            ),
            *(
                state.chapter
                for states in self.knowledge.character_states.values()
                for state in states
            ),
            *(item.created_chapter for item in self.knowledge.foreshadowings),
            *(
                item.resolved_chapter
                for item in self.knowledge.foreshadowings
                if item.resolved_chapter is not None
            ),
            *(item.chapter for item in self.knowledge.timeline),
            *self.knowledge.chapter_summaries.keys(),
            *self.knowledge.chapter_constraints.keys(),
            *(item.chapter for item in self.knowledge.retrieval_notes),
        }
        orphaned = referenced_indexes - source_indexes
        if orphaned:
            raise ValueError(
                "Derived knowledge has no matching manuscript provenance: "
                + ", ".join(str(index) for index in sorted(orphaned))
            )

    def generation_view(self, chapter_index: int) -> Story:
        """Return canonical history visible while generating one chapter.

        The target chapter keeps only its scene plan. Its old prose, derived
        knowledge, and every future chapter are hidden from the model.
        """
        view = self.model_copy(deep=True)
        target = view.manuscript.chapters.get(chapter_index)
        view.manuscript.chapters = {
            index: chapter
            for index, chapter in view.manuscript.chapters.items()
            if index < chapter_index
        }
        if target is not None and target.beats:
            target.content = ""
            target.history = []
            view.manuscript.chapters[chapter_index] = target

        knowledge = view.knowledge
        knowledge.sources = {
            index: source for index, source in knowledge.sources.items() if index < chapter_index
        }
        knowledge.character_observations = [
            item for item in knowledge.character_observations if item.source_chapter < chapter_index
        ]
        knowledge.world_facts = [
            item for item in knowledge.world_facts if item.source_chapter < chapter_index
        ]
        knowledge.relationships = [
            item for item in knowledge.relationships if item.source_chapter < chapter_index
        ]
        knowledge.character_facts = [
            item
            for item in knowledge.character_facts
            if item.source_chapter is None or item.source_chapter < chapter_index
        ]
        knowledge.character_states = {
            character_id: [state for state in states if state.chapter < chapter_index]
            for character_id, states in knowledge.character_states.items()
        }
        knowledge.foreshadowings = [
            item for item in knowledge.foreshadowings if item.created_chapter < chapter_index
        ]
        knowledge.timeline = [item for item in knowledge.timeline if item.chapter < chapter_index]
        knowledge.chapter_summaries = {
            index: summary
            for index, summary in knowledge.chapter_summaries.items()
            if index < chapter_index
        }
        knowledge.volume_summaries = [
            item for item in knowledge.volume_summaries if item.chapter_range[1] < chapter_index
        ]
        knowledge.arc_summaries = [
            item for item in knowledge.arc_summaries if item.chapter_range[1] < chapter_index
        ]
        knowledge.chapter_constraints = {
            index: constraints
            for index, constraints in knowledge.chapter_constraints.items()
            if index < chapter_index
        }
        knowledge.retrieval_notes = [
            item for item in knowledge.retrieval_notes if item.chapter < chapter_index
        ]
        return view


__all__ = [
    "Manuscript",
    "Story",
    "StoryDesign",
    "StoryKnowledge",
    "StoryQuality",
    "StoryRuns",
    "StoryStatus",
]
