"""Typed HTTP request and response contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from novelforge.domain import (
    Chapter,
    ChapterContract,
    ChapterOutline,
    Character,
    CharacterFact,
    ReviewReport,
    Story,
    WorldSetting,
)


class CreateStoryRequest(BaseModel):
    premise: str = Field(min_length=1)
    title: str = "Untitled Novel"
    genre: str = "novel"
    style_guide: str = ""


class OutlineRequest(BaseModel):
    num_chapters: int | None = Field(default=None, ge=1)
    force: bool = False


class BatchWriteRequest(BaseModel):
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)


class AgentGoalRequest(BaseModel):
    goal: str = Field(min_length=1)
    max_steps: int = Field(default=12, ge=1, le=100)


class AgentResumeRequest(BaseModel):
    user_input: str = ""


class RevisionRequest(BaseModel):
    instruction: str = Field(min_length=1)


class ChapterContentRequest(BaseModel):
    title: str | None = None
    content: str = Field(min_length=1)
    status: str = "draft"


class ChapterContractRequest(ChapterContract):
    pass


class CharacterFactRequest(CharacterFact):
    pass


class CharacterRequest(Character):
    pass


class WorldSettingRequest(WorldSetting):
    pass


class StoryResponse(BaseModel):
    story: Story


class OutlineResponse(BaseModel):
    outlines: list[ChapterOutline]


class ChapterResponse(BaseModel):
    chapter: Chapter


class ReviewResponse(BaseModel):
    report: ReviewReport


class StatusResponse(BaseModel):
    story_id: str
    title: str
    status: str
    current_chapter: int
    extra: dict = Field(default_factory=dict)


__all__ = [
    "AgentGoalRequest",
    "AgentResumeRequest",
    "BatchWriteRequest",
    "ChapterContentRequest",
    "ChapterContractRequest",
    "ChapterResponse",
    "CharacterFactRequest",
    "CharacterRequest",
    "CreateStoryRequest",
    "OutlineRequest",
    "OutlineResponse",
    "ReviewResponse",
    "RevisionRequest",
    "StatusResponse",
    "StoryResponse",
    "WorldSettingRequest",
]
