"""Persisted evaluations and approval-gated revision decisions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from novelforge.domain.common import DomainModel, utc_now
from novelforge.domain.knowledge import CharacterState


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"


class ProposalStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class GenerationDecision(StrEnum):
    ACCEPT = "accept"
    REPAIR = "repair"
    REJECT = "reject"


class ConstraintCheck(DomainModel):
    constraint_type: str
    requirement: str
    passed: bool
    severity: Severity = Severity.HIGH
    evidence: str = ""
    message: str = ""
    status: CheckStatus = CheckStatus.PASSED
    rule_passed: bool | None = None
    semantic_passed: bool | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    paragraph_range: str = ""
    validation_method: str = "rule"


class ReviewReport(DomainModel):
    logic_issues: list[str] = Field(default_factory=list)
    character_issues: list[str] = Field(default_factory=list)
    pacing_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    verdict: str = "needs_revision"


class QualityScores(DomainModel):
    logic_consistency: float = Field(default=0.0, ge=0.0, le=10.0)
    character_fidelity: float = Field(default=0.0, ge=0.0, le=10.0)
    foreshadowing_handling: float = Field(default=0.0, ge=0.0, le=10.0)
    pacing: float = Field(default=0.0, ge=0.0, le=10.0)
    style_uniformity: float = Field(default=0.0, ge=0.0, le=10.0)

    def weighted_total(self, weights: dict[str, float] | None = None) -> float:
        active = weights or {
            "logic_consistency": 0.25,
            "character_fidelity": 0.25,
            "foreshadowing_handling": 0.20,
            "pacing": 0.15,
            "style_uniformity": 0.15,
        }
        total_weight = sum(active.values()) or 1.0
        return round(
            sum(getattr(self, name, 0.0) * weight for name, weight in active.items())
            / total_weight,
            2,
        )


class RevisionIssue(DomainModel):
    dimension: str
    severity: Severity = Severity.MEDIUM
    description: str
    paragraph_range: str = ""
    evidence: str = ""


class ContinuityIssue(DomainModel):
    dimension: str
    severity: Severity = Severity.MEDIUM
    description: str
    evidence: str = ""
    suggestion: str = ""


class ContinuityAuditReport(DomainModel):
    chapter_index: int = Field(ge=1)
    risk_score: float = Field(default=0.0, ge=0.0, le=10.0)
    passed: bool = True
    issues: list[ContinuityIssue] = Field(default_factory=list)
    checked_constraints: list[str] = Field(default_factory=list)
    summary: str = ""
    audit_method: str = "llm"


class QualityReviewReport(DomainModel):
    scores: QualityScores = Field(default_factory=QualityScores)
    issues: list[RevisionIssue] = Field(default_factory=list)
    overall_comment: str = ""
    contract_checks: list[ConstraintCheck] = Field(default_factory=list)
    hard_constraints_passed: bool = True

    def total_score(self, weights: dict[str, float] | None = None) -> float:
        return self.scores.weighted_total(weights)


class GenerationAttemptReport(DomainModel):
    attempt: int = Field(ge=1)
    contract_checks: list[ConstraintCheck] = Field(default_factory=list)
    continuity: ContinuityAuditReport
    quality: QualityReviewReport
    score: float = Field(ge=0.0, le=10.0)
    decision: GenerationDecision
    reasons: list[str] = Field(default_factory=list)


class ChapterGenerationReport(DomainModel):
    chapter_index: int = Field(ge=1)
    accepted: bool
    attempts: list[GenerationAttemptReport] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class CharacterContinuityIssue(DomainModel):
    chapter_index: int = Field(ge=1)
    dimension: str
    severity: Severity = Severity.MEDIUM
    description: str
    evidence: str = ""
    suggestion: str = ""
    previous_chapter: int | None = Field(default=None, ge=1)


class CharacterContinuityReport(DomainModel):
    character_id: str
    character_name: str = ""
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)
    trajectory: list[CharacterState] = Field(default_factory=list)
    issues: list[CharacterContinuityIssue] = Field(default_factory=list)
    affected_chapters: list[int] = Field(default_factory=list)
    passed: bool = True
    summary: str = ""


class RevisionProposal(DomainModel):
    id: str = Field(default_factory=lambda: f"proposal-{uuid4().hex[:12]}")
    story_id: str
    chapter_index: int = Field(ge=1)
    source_version: int = Field(ge=1)
    instruction: str
    original_content: str
    proposed_content: str
    review_report: ReviewReport
    validation_report: ChapterGenerationReport
    eligible: bool = False
    status: ProposalStatus = ProposalStatus.AWAITING_APPROVAL
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StoryQuality(DomainModel):
    review_reports: dict[int, ReviewReport] = Field(default_factory=dict)
    generation_reports: dict[int, ChapterGenerationReport] = Field(default_factory=dict)
    continuity_reports: dict[int, ContinuityAuditReport] = Field(default_factory=dict)
    character_continuity_reports: list[CharacterContinuityReport] = Field(default_factory=list)
    revision_proposals: list[RevisionProposal] = Field(default_factory=list)


__all__ = [
    "ChapterGenerationReport",
    "CharacterContinuityIssue",
    "CharacterContinuityReport",
    "CheckStatus",
    "ConstraintCheck",
    "ContinuityAuditReport",
    "ContinuityIssue",
    "GenerationAttemptReport",
    "GenerationDecision",
    "ProposalStatus",
    "QualityReviewReport",
    "QualityScores",
    "ReviewReport",
    "RevisionIssue",
    "RevisionProposal",
    "Severity",
    "StoryQuality",
]
