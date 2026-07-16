"""Operational state for resumable, observable agent work."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from novelforge.domain.common import DomainModel, utc_now
from novelforge.domain.manuscript import Chapter


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CandidateStatus(StrEnum):
    DRAFT = "draft"
    EVALUATING = "evaluating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMMITTED = "committed"
    STALE = "stale"


class AgentRun(DomainModel):
    """One user goal executed by the orchestrator.

    This is operational state. It is deliberately not part of the Story
    aggregate and can be retained, archived, or deleted independently.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    goal: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    plan: list[dict[str, Any]] = Field(default_factory=list)
    current_step: int = Field(default=0, ge=0)
    max_steps: int = Field(default=12, ge=1, le=100)
    story_revision: int = Field(default=0, ge=0)
    provider: str = ""
    model: str = ""
    result_summary: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AgentStep(DomainModel):
    """One observable decision and tool execution within an AgentRun."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: int = Field(ge=1)
    agent_name: str
    action: str
    tool_name: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    status: AgentStepStatus = AgentStepStatus.RUNNING
    decision_summary: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)
    error: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class ChapterCandidateRecord(DomainModel):
    """A generated chapter that has not necessarily entered canon."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    story_id: UUID
    chapter_index: int = Field(ge=1)
    source_story_revision: int = Field(ge=0)
    status: CandidateStatus = CandidateStatus.DRAFT
    chapter: Chapter
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CandidateEvaluationRecord(DomainModel):
    """Structured evidence produced by one candidate evaluator."""

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    evaluator: str
    passed: bool
    score: float | None = Field(default=None, ge=0.0, le=10.0)
    issues: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "AgentStep",
    "AgentStepStatus",
    "CandidateEvaluationRecord",
    "CandidateStatus",
    "ChapterCandidateRecord",
]
