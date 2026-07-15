"""Author-controlled story design and generation constraints."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from novelforge.domain.common import DomainModel


class Character(DomainModel):
    id: str
    name: str
    age: int | str = "unknown"
    appearance: str = ""
    personality: str = ""
    motivation: str = ""
    weakness: str = ""
    relationships: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    arc: str = ""


class WorldSetting(DomainModel):
    id: str
    category: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChapterOutline(DomainModel):
    chapter_index: int = Field(ge=1)
    title: str
    summary: str
    conflict: str
    pov_character: str | None = None


class ChapterContract(DomainModel):
    """Hard, author-editable acceptance criteria for one chapter."""

    chapter_index: int = Field(ge=1)
    pov_character: str | None = None
    location: str = ""
    time_context: str = ""
    must_happen: list[str] = Field(default_factory=list)
    must_not_happen: list[str] = Field(default_factory=list)
    character_goals: dict[str, str] = Field(default_factory=dict)
    knowledge_boundaries: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    active_threads: list[str] = Field(default_factory=list)
    ending_hook: str = ""
    style_requirements: list[str] = Field(default_factory=list)
    notes: str = ""


class StoryDesign(DomainModel):
    """Intent supplied by the author or explicitly promoted by a use case."""

    characters: dict[str, Character] = Field(default_factory=dict)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    outlines: list[ChapterOutline] = Field(default_factory=list)
    chapter_contracts: dict[int, ChapterContract] = Field(default_factory=dict)


__all__ = [
    "ChapterContract",
    "ChapterOutline",
    "Character",
    "StoryDesign",
    "WorldSetting",
]
