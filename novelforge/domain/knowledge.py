"""Canonical knowledge derived from committed manuscript versions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from novelforge.domain.common import DomainModel, utc_now


class ForeshadowingStatus(StrEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    ABANDONED = "abandoned"


class Foreshadowing(DomainModel):
    id: str
    description: str
    created_chapter: int = Field(ge=1)
    target_chapter: int | None = Field(default=None, ge=1)
    status: ForeshadowingStatus = ForeshadowingStatus.PENDING
    resolved_chapter: int | None = Field(default=None, ge=1)
    notes: str = ""


class TimelineEvent(DomainModel):
    id: str
    chapter: int = Field(ge=1)
    description: str
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)


class CharacterState(DomainModel):
    character_id: str
    chapter: int = Field(ge=1)
    emotional_state: str = ""
    location: str = ""
    knowledge_gained: list[str] = Field(default_factory=list)
    relationship_changes: dict[str, str] = Field(default_factory=dict)


class CharacterFact(DomainModel):
    id: str = Field(default_factory=lambda: f"fact-{uuid4().hex[:12]}")
    character_id: str
    fact_type: str
    value: str
    valid_from_chapter: int = Field(ge=1)
    valid_until_chapter: int | None = Field(default=None, ge=1)
    source_chapter: int | None = Field(default=None, ge=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_confirmed: bool = False
    notes: str = ""


class ChapterSummary(DomainModel):
    chapter_index: int = Field(ge=1)
    scene_summaries: list[str] = Field(default_factory=list)
    chapter_summary: str = ""
    key_events: list[str] = Field(default_factory=list)


class VolumeSummary(DomainModel):
    volume: int = Field(ge=1)
    chapter_range: tuple[int, int]
    summary: str = ""


class ArcSummary(DomainModel):
    arc: int = Field(ge=1)
    chapter_range: tuple[int, int]
    summary: str = ""
    key_threads: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class StoryGuide(DomainModel):
    core_premise: str = ""
    style_guide: str = ""
    current_direction: str = ""
    active_threads: list[str] = Field(default_factory=list)
    character_roster: dict[str, str] = Field(default_factory=dict)
    world_rules: list[str] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class RetrievalNote(DomainModel):
    """Compact canonical retrieval input; vector embeddings remain disposable."""

    id: str
    type: str
    content: str
    chapter: int = Field(ge=1)
    importance: int = Field(default=5, ge=1, le=10)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    last_seen_chapter: int | None = Field(default=None, ge=1)


class CharacterObservation(DomainModel):
    """A prose-supported character profile, separate from author intent."""

    character_id: str
    name: str
    appearance: str = ""
    personality: str = ""
    motivation: str = ""
    source_chapter: int = Field(ge=1)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class WorldFact(DomainModel):
    """A world detail observed in committed prose."""

    fact_id: str
    category: str
    content: str
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    source_chapter: int = Field(ge=1)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class RelationshipFact(DomainModel):
    source: str
    target: str
    relation: str
    source_chapter: int = Field(ge=1)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeSource(DomainModel):
    """Exact manuscript revision from which a chapter projection was derived."""

    chapter_index: int = Field(ge=1)
    manuscript_version: int = Field(ge=1)
    content_digest: str
    processed_at: datetime = Field(default_factory=utc_now)


class StoryKnowledge(DomainModel):
    """Facts derived from prose, keyed to the exact source chapter version."""

    sources: dict[int, KnowledgeSource] = Field(default_factory=dict)
    character_observations: list[CharacterObservation] = Field(default_factory=list)
    world_facts: list[WorldFact] = Field(default_factory=list)
    relationships: list[RelationshipFact] = Field(default_factory=list)
    character_facts: list[CharacterFact] = Field(default_factory=list)
    character_states: dict[str, list[CharacterState]] = Field(default_factory=dict)
    foreshadowings: list[Foreshadowing] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    chapter_summaries: dict[int, ChapterSummary] = Field(default_factory=dict)
    volume_summaries: list[VolumeSummary] = Field(default_factory=list)
    arc_summaries: list[ArcSummary] = Field(default_factory=list)
    guide: StoryGuide = Field(default_factory=StoryGuide)
    chapter_constraints: dict[int, list[str]] = Field(default_factory=dict)
    retrieval_notes: list[RetrievalNote] = Field(default_factory=list)

    def is_current(
        self,
        chapter_index: int,
        manuscript_version: int,
        content_digest: str | None = None,
    ) -> bool:
        source = self.sources.get(chapter_index)
        return bool(
            source
            and source.manuscript_version == manuscript_version
            and (content_digest is None or source.content_digest == content_digest)
        )


class ChapterKnowledgeDelta(DomainModel):
    """Complete replacement projection for one exact chapter version."""

    chapter_index: int = Field(ge=1)
    source: KnowledgeSource
    summary: ChapterSummary
    character_observations: list[CharacterObservation] = Field(default_factory=list)
    world_facts: list[WorldFact] = Field(default_factory=list)
    relationships: list[RelationshipFact] = Field(default_factory=list)
    character_facts: list[CharacterFact] = Field(default_factory=list)
    character_states: list[CharacterState] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    foreshadowings: list[Foreshadowing] = Field(default_factory=list)
    retrieval_notes: list[RetrievalNote] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)


__all__ = [
    "ArcSummary",
    "ChapterKnowledgeDelta",
    "ChapterSummary",
    "CharacterFact",
    "CharacterObservation",
    "CharacterState",
    "Foreshadowing",
    "ForeshadowingStatus",
    "KnowledgeSource",
    "RetrievalNote",
    "RelationshipFact",
    "StoryGuide",
    "StoryKnowledge",
    "TimelineEvent",
    "VolumeSummary",
    "WorldFact",
]
