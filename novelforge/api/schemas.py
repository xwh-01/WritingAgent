"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from novelforge.core.models import Chapter, ChapterOutline, ReviewReport, Story


class CreateStoryRequest(BaseModel):
    premise: str
    title: str = "Untitled Novel"
    genre: str = "novel"
    style_guide: str = ""


class OutlineRequest(BaseModel):
    num_chapters: int | None = None


class BatchWriteRequest(BaseModel):
    start_chapter: int
    end_chapter: int
    use_auto_revision: bool = True
    background: bool = True


class ReviseRequest(BaseModel):
    revised_content: str | None = None


class ChapterContentRequest(BaseModel):
    title: str | None = None
    content: str
    status: str = "draft"


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
    extra: dict[str, Any] = {}
