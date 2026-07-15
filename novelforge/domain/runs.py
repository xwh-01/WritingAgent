"""Operational reports which never become story facts."""

from __future__ import annotations

from pydantic import Field

from novelforge.domain.common import DomainModel


class BatchChapterResult(DomainModel):
    chapter_index: int = Field(ge=1)
    status: str
    title: str = ""
    character_count: int = 0
    quality_score: float | None = Field(default=None, ge=0.0, le=10.0)
    message: str = ""


class BatchWriteReport(DomainModel):
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)
    results: list[BatchChapterResult] = Field(default_factory=list)
    completed: int = 0
    failed: int = 0


class StoryRuns(DomainModel):
    batch_reports: list[BatchWriteReport] = Field(default_factory=list)


__all__ = ["BatchChapterResult", "BatchWriteReport", "StoryRuns"]
