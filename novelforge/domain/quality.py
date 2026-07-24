"""Persisted evaluations and approval-gated revision decisions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from novelforge.domain.common import DomainModel, utc_now
from novelforge.domain.knowledge import CharacterState
from novelforge.domain.manuscript import ScenePatch


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


class ContractConflict(DomainModel):
    """A contradiction that makes a chapter contract impossible to execute safely."""

    code: str
    message: str
    requirements: list[str] = Field(default_factory=list)
    severity: Severity = Severity.CRITICAL


class SceneObligation(DomainModel):
    """One contract requirement assigned to an executable scene."""

    id: str
    constraint_type: str
    requirement: str
    scene_index: int = Field(ge=1)
    severity: Severity = Severity.HIGH
    mode: str = "must_include"
    source: str = "chapter_contract"


class ContractExecutionPlan(DomainModel):
    """Traceable ChapterContract-to-scene assignment produced before drafting."""

    chapter_index: int = Field(ge=1)
    obligations: list[SceneObligation] = Field(default_factory=list)
    conflicts: list[ContractConflict] = Field(default_factory=list)

    @property
    def is_executable(self) -> bool:
        return not self.conflicts

    def obligations_for_scene(self, scene_index: int) -> list[SceneObligation]:
        return [item for item in self.obligations if item.scene_index == scene_index]


class ContractEvidence(DomainModel):
    """Evidence span and decision for an obligation after a generation attempt."""

    obligation_id: str
    scene_index: int = Field(ge=1)
    constraint_type: str
    requirement: str
    passed: bool
    status: CheckStatus = CheckStatus.REVIEW_REQUIRED
    evidence: str = ""
    paragraph_range: str = ""
    failure_category: str = ""


class ContractEvidenceLedger(DomainModel):
    """Attempt-local proof ledger consumed by targeted scene repair and APIs."""

    chapter_index: int = Field(ge=1)
    plan: ContractExecutionPlan
    entries: list[ContractEvidence] = Field(default_factory=list)

    @property
    def failed_entries(self) -> list[ContractEvidence]:
        return [item for item in self.entries if not item.passed]


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


class ContractReviewEvidence(DomainModel):
    """One cited semantic decision returned by the shared generation review."""

    obligation_id: str
    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    paragraph_range: str = ""


class UnifiedReviewBundle(DomainModel):
    """One shared-model assessment for craft, continuity, character, and contract risks."""

    quality: QualityReviewReport = Field(default_factory=QualityReviewReport)
    continuity: ContinuityAuditReport
    character_risks: list[ContinuityIssue] = Field(default_factory=list)
    contract_evidence: list[ContractReviewEvidence] = Field(default_factory=list)


class GenerationReviewPayload(DomainModel):
    """Compact wire schema for the single generation-review model call."""

    scores: QualityScores = Field(default_factory=QualityScores)
    quality_issues: list[RevisionIssue] = Field(default_factory=list)
    quality_comment: str = ""
    continuity_passed: bool = True
    continuity_risk_score: float = Field(default=0.0, ge=0.0, le=10.0)
    continuity_issues: list[ContinuityIssue] = Field(default_factory=list)
    continuity_summary: str = ""
    character_risks: list[ContinuityIssue] = Field(default_factory=list)
    contract_evidence: list[ContractReviewEvidence] = Field(default_factory=list)


class SceneCandidateSelection(DomainModel):
    """Blind quality choice made after every candidate passed hard constraints."""

    scene_index: int = Field(ge=1)
    candidate_ids: list[str] = Field(default_factory=list)
    selected_id: str
    reason: str = ""
    scores: dict[str, float] = Field(default_factory=dict)


class GenerationBudgetReport(DomainModel):
    """Actual chapter-generation resource usage and the enforced envelope."""

    max_calls: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    calls_used: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    estimated_tokens_used: bool = False
    exhausted_reason: str = ""
    operations: list[str] = Field(default_factory=list)


class GenerationAttemptReport(DomainModel):
    attempt: int = Field(ge=1)
    contract_checks: list[ConstraintCheck] = Field(default_factory=list)
    continuity: ContinuityAuditReport
    quality: QualityReviewReport
    score: float = Field(ge=0.0, le=10.0)
    decision: GenerationDecision
    reasons: list[str] = Field(default_factory=list)
    execution_plan: ContractExecutionPlan | None = None
    evidence_ledger: ContractEvidenceLedger | None = None
    review_mode: str = "full"
    repair_obligation_ids: list[str] = Field(default_factory=list)
    changed_scene_indexes: list[int] = Field(default_factory=list)


class ChapterGenerationReport(DomainModel):
    chapter_index: int = Field(ge=1)
    accepted: bool
    attempts: list[GenerationAttemptReport] = Field(default_factory=list)
    candidate_selections: list[SceneCandidateSelection] = Field(default_factory=list)
    budget: GenerationBudgetReport | None = None
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
    scene_patches: list[ScenePatch] = Field(default_factory=list)
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


__all__ = [
    "ChapterGenerationReport",
    "CharacterContinuityIssue",
    "CharacterContinuityReport",
    "CheckStatus",
    "ContractReviewEvidence",
    "ConstraintCheck",
    "ContinuityAuditReport",
    "ContinuityIssue",
    "GenerationAttemptReport",
    "GenerationBudgetReport",
    "GenerationDecision",
    "GenerationReviewPayload",
    "ProposalStatus",
    "QualityReviewReport",
    "QualityScores",
    "ReviewReport",
    "RevisionIssue",
    "RevisionProposal",
    "Severity",
    "SceneCandidateSelection",
    "StoryQuality",
]
