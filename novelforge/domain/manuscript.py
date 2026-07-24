"""Committed prose, scene hand-offs, and immutable chapter history."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import Field, model_validator

from novelforge.domain.common import DomainModel, content_digest, utc_now


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

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_container_mismatches(cls, value: Any) -> Any:
        """Accept harmless empty `{}`/`[]` swaps from structured LLM output.

        These swaps occur frequently when a model has no relationship or state
        changes to report.  Only empty containers are normalized; non-empty
        values still fail validation so malformed continuity facts are never
        silently coerced.
        """
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for name in (
            "characters_present",
            "relationship_changes",
            "promises",
            "questions_created",
            "questions_resolved",
        ):
            if normalized.get(name) == {}:
                normalized[name] = []
        for name in (
            "character_state_changes",
            "location_changes",
            "knowledge_gained",
            "items_gained",
            "items_lost",
            "injuries_or_conditions",
            "decisions",
            "ending_state",
        ):
            if normalized.get(name) == []:
                normalized[name] = {}
        return normalized


class SceneDraft(DomainModel):
    content: str
    ending_state: SceneEndState = Field(default_factory=SceneEndState)


class ScenePatch(DomainModel):
    """One auditable mutation of an already planned scene.

    Generated prose may only mutate a composed chapter through these patches.
    ``source_content_digest`` makes a patch safe to apply after asynchronous
    review: a stale patch cannot silently overwrite a newer scene revision.
    """

    scene_index: int = Field(ge=1)
    content: str = Field(min_length=1)
    ending_state: SceneEndState | None = None
    reason: str = ""
    source_content_digest: str = ""


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
    contract_obligations: list[dict[str, Any]] = Field(default_factory=list)
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

    SCENE_SEPARATOR: ClassVar[str] = "\n\n***\n\n"

    def merged_scene_content(self) -> str:
        """Return the canonical chapter prose derived from completed scene prose."""
        ordered = sorted(self.beats, key=lambda item: item.scene_index)
        if any(not item.content.strip() for item in ordered):
            raise ValueError("Cannot merge a chapter with an empty scene.")
        return self.SCENE_SEPARATOR.join(item.content.strip() for item in ordered)

    def scene_content_is_current(self) -> bool:
        """Whether the chapter cache is exactly the merge of its scene source of truth."""
        if not self.beats:
            return True
        try:
            return self.content == self.merged_scene_content()
        except ValueError:
            return False

    def sync_content_from_scenes(self) -> None:
        """Refresh the chapter cache after scene creation or a ScenePatch application."""
        if self.beats:
            self.content = self.merged_scene_content()

    def apply_scene_patches(self, patches: list[ScenePatch]) -> tuple[int, ...]:
        """Apply non-stale scene patches atomically and rebuild the chapter cache.

        The operation validates every patch before mutating a beat, so a stale
        or duplicate patch leaves the chapter untouched rather than producing a
        mixed-version manuscript.
        """
        if not patches:
            return ()
        by_index = {item.scene_index: item for item in patches}
        if len(by_index) != len(patches):
            raise ValueError("A scene may receive at most one patch per mutation.")
        beats = {item.scene_index: item for item in self.beats}
        missing = sorted(set(by_index).difference(beats))
        if missing:
            raise ValueError(f"Scene patch references unknown scenes: {missing}.")
        for scene_index, patch in by_index.items():
            scene = beats[scene_index]
            if patch.source_content_digest and patch.source_content_digest != content_digest(scene.content):
                raise ValueError(f"Scene patch for scene {scene_index} is stale.")
        for scene_index, patch in by_index.items():
            scene = beats[scene_index]
            scene.content = patch.content.strip()
            if patch.ending_state is not None:
                scene.end_state = patch.ending_state.model_dump()
            scene.status = SceneStatus.COMPLETED
        self.sync_content_from_scenes()
        return tuple(sorted(by_index))

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
    "ScenePatch",
    "SceneStatus",
]
