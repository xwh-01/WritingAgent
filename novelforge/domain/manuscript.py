"""Committed prose, scene hand-offs, and immutable chapter history."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from novelforge.domain.common import DomainModel, utc_now


class SceneStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"


class ChapterStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    REVISED = "revised"
    FINALIZED = "finalized"


class SceneEndState(DomainModel):
    """Typed hand-off between adjacent generated scenes."""

    characters_present: list[str] = Field(default_factory=list)
    character_state_changes: dict[str, str] = Field(default_factory=dict)
    relationship_changes: list[str] = Field(default_factory=list)
    location_changes: dict[str, str] = Field(default_factory=dict)
    time_changes: str = ""
    knowledge_gained: dict[str, list[str]] = Field(default_factory=dict)
    items_gained: dict[str, list[str]] = Field(default_factory=dict)
    items_lost: dict[str, list[str]] = Field(default_factory=dict)
    injuries_or_conditions: dict[str, str] = Field(default_factory=dict)
    decisions: dict[str, str] = Field(default_factory=dict)
    promises: list[str] = Field(default_factory=list)
    questions_created: list[str] = Field(default_factory=list)
    questions_resolved: list[str] = Field(default_factory=list)
    ending_state: dict[str, Any] = Field(default_factory=dict)


class SceneDraft(DomainModel):
    content: str
    ending_state: SceneEndState = Field(default_factory=SceneEndState)


class Beat(DomainModel):
    """A scene plan which becomes a generated scene after completion."""

    scene_index: int = Field(default=0, ge=0)
    description: str = ""
    goal: str = ""
    outcome: str = ""
    title: str = ""
    purpose: str = ""
    pov_character: str = ""
    location: str = ""
    time_context: str = ""
    participating_characters: list[str] = Field(default_factory=list)
    character_goals: dict[str, str] = Field(default_factory=dict)
    conflict: str = ""
    obstacle: str = ""
    must_happen: list[str] = Field(default_factory=list)
    must_not_happen: list[str] = Field(default_factory=list)
    information_revealed: list[str] = Field(default_factory=list)
    start_state: dict[str, Any] = Field(default_factory=dict)
    end_state: dict[str, Any] = Field(default_factory=dict)
    transition_to_next: str = ""
    target_length: int = 0
    content: str = ""
    status: SceneStatus = SceneStatus.PLANNED


class ChapterVersion(DomainModel):
    version: int = Field(ge=1)
    content: str
    status: ChapterStatus
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class Chapter(DomainModel):
    """One committed chapter; unaccepted candidates live outside Manuscript."""

    index: int = Field(ge=1)
    title: str
    content: str = ""
    version: int = Field(default=1, ge=1)
    status: ChapterStatus = ChapterStatus.DRAFT
    summary: str = ""
    beats: list[Beat] = Field(default_factory=list)
    history: list[ChapterVersion] = Field(default_factory=list)

    def snapshot(self) -> ChapterVersion:
        return ChapterVersion(
            version=self.version,
            content=self.content,
            status=self.status,
            summary=self.summary,
        )

    def replace_content(
        self,
        content: str,
        *,
        status: ChapterStatus | str | None = None,
        summary: str | None = None,
    ) -> None:
        """Replace official prose while preserving the previous version exactly once."""
        if self.content:
            self.history.append(self.snapshot())
            self.version += 1
        self.content = content
        if status is not None:
            self.status = ChapterStatus(status)
        if summary is not None:
            self.summary = summary


class Manuscript(DomainModel):
    chapters: dict[int, Chapter] = Field(default_factory=dict)


__all__ = [
    "Beat",
    "Chapter",
    "ChapterStatus",
    "ChapterVersion",
    "Manuscript",
    "SceneDraft",
    "SceneEndState",
    "SceneStatus",
]
