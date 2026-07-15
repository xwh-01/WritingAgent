"""Reliable chapter generation as explicit candidate, gate, repair, and decision stages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from novelforge.domain import (
    Chapter,
    ChapterContract,
    ChapterGenerationReport,
    ChapterOutline,
    ConstraintCheck,
    ContinuityAuditReport,
    GenerationAttemptReport,
    GenerationDecision,
    QualityReviewReport,
    RevisionIssue,
    Story,
)


@dataclass(frozen=True)
class GenerationPolicy:
    min_quality_score: float = 7.5
    max_repairs: int = 2
    blocking_severities: frozenset[str] = frozenset({"high", "critical"})
    require_contract_pass: bool = True
    require_continuity_pass: bool = True


@dataclass(frozen=True)
class ChapterAssessment:
    attempt: int
    contract_checks: tuple[ConstraintCheck, ...]
    continuity: ContinuityAuditReport
    quality: QualityReviewReport
    score: float
    decision: GenerationDecision
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationOutcome:
    candidate: Chapter
    accepted: bool
    assessments: tuple[ChapterAssessment, ...] = ()

    @property
    def final_assessment(self) -> ChapterAssessment:
        if not self.assessments:
            raise RuntimeError("Generation outcome has no assessment.")
        return self.assessments[-1]

    def to_report(self) -> ChapterGenerationReport:
        return ChapterGenerationReport(
            chapter_index=self.candidate.index,
            accepted=self.accepted,
            attempts=[
                GenerationAttemptReport(
                    attempt=item.attempt,
                    contract_checks=list(item.contract_checks),
                    continuity=item.continuity,
                    quality=item.quality,
                    score=item.score,
                    decision=item.decision,
                    reasons=list(item.reasons),
                )
                for item in self.assessments
            ],
        )


class ComposerPort(Protocol):
    def compose(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        context: str,
        polish_draft: Callable[[Story, int, str], str],
    ) -> Chapter: ...


class ContextPort(Protocol):
    def build(self, chapter_index: int, story: Story) -> str: ...


class ContractValidatorPort(Protocol):
    def validate(self, content: str, contract: ChapterContract | None) -> list[ConstraintCheck]: ...


class ContinuityAuditorPort(Protocol):
    def audit_chapter(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        context: str,
    ) -> ContinuityAuditReport: ...


class CriticPort(Protocol):
    def review_quality_scorecard(
        self,
        content: str,
        chapter_outline: ChapterOutline,
        story: Story,
        extra_context: str = "",
    ) -> QualityReviewReport: ...


class EditorPort(Protocol):
    def revise_from_quality_report(
        self,
        chapter_content: str,
        quality_report: QualityReviewReport,
        style_guide: str = "",
    ) -> str: ...


class CandidateEvaluator:
    """Evaluate a candidate without mutating Story or Manuscript."""

    def __init__(
        self,
        contracts: ContractValidatorPort,
        continuity: ContinuityAuditorPort,
        critic: CriticPort,
        policy: GenerationPolicy,
    ) -> None:
        self.contracts = contracts
        self.continuity = continuity
        self.critic = critic
        self.policy = policy

    def evaluate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        context: str,
        attempt: int,
    ) -> ChapterAssessment:
        checks = self.contracts.validate(candidate.content, contract)
        continuity = self.continuity.audit_chapter(
            story,
            candidate.index,
            candidate.content,
            context,
        )
        quality = self.critic.review_quality_scorecard(
            candidate.content,
            outline,
            story,
            extra_context=context,
        )
        quality.contract_checks = checks

        reasons: list[str] = []
        failed_checks = [check for check in checks if not check.passed]
        if self.policy.require_contract_pass and failed_checks:
            reasons.extend(f"contract:{check.constraint_type}" for check in failed_checks)
            quality.hard_constraints_passed = False
            quality.issues.extend(self._contract_issues(failed_checks))

        blocking_continuity = [
            issue
            for issue in continuity.issues
            if str(issue.severity) in self.policy.blocking_severities
        ]
        if self.policy.require_continuity_pass and (not continuity.passed or blocking_continuity):
            reasons.extend(f"continuity:{issue.dimension}" for issue in blocking_continuity)
            if not blocking_continuity:
                reasons.append("continuity:audit_failed")
            quality.issues.extend(self._continuity_issues(continuity))

        score = quality.total_score()
        if score < self.policy.min_quality_score:
            reasons.append(f"quality:{score:.2f}<{self.policy.min_quality_score:.2f}")

        blocking_quality = [
            issue
            for issue in quality.issues
            if str(issue.severity) in self.policy.blocking_severities
        ]
        if blocking_quality:
            reasons.extend(f"quality_issue:{issue.dimension}" for issue in blocking_quality)

        if not reasons:
            decision = GenerationDecision.ACCEPT
        elif attempt <= self.policy.max_repairs:
            decision = GenerationDecision.REPAIR
        else:
            decision = GenerationDecision.REJECT
        return ChapterAssessment(
            attempt=attempt,
            contract_checks=tuple(checks),
            continuity=continuity,
            quality=quality,
            score=score,
            decision=decision,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _contract_issues(checks: list[ConstraintCheck]) -> list[RevisionIssue]:
        return [
            RevisionIssue(
                dimension=f"contract:{check.constraint_type}",
                severity=check.severity,
                description=check.message or f"Unmet requirement: {check.requirement}",
                paragraph_range=check.paragraph_range,
                evidence=check.evidence,
            )
            for check in checks
        ]

    @staticmethod
    def _continuity_issues(report: ContinuityAuditReport) -> list[RevisionIssue]:
        return [
            RevisionIssue(
                dimension=f"continuity:{issue.dimension}",
                severity=issue.severity,
                description=issue.description,
                evidence=issue.evidence,
            )
            for issue in report.issues
        ]


class ChapterGenerationPipeline:
    """Generate and repair candidates; never commit a rejected candidate."""

    def __init__(
        self,
        composer: ComposerPort,
        context: ContextPort,
        evaluator: CandidateEvaluator,
        editor: EditorPort,
    ) -> None:
        self.composer = composer
        self.context = context
        self.evaluator = evaluator
        self.editor = editor

    def generate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        polish_draft: Callable[[Story, int, str], str],
    ) -> GenerationOutcome:
        source = story.generation_view(outline.chapter_index)
        context = self.context.build(outline.chapter_index, source)
        candidate = self.composer.compose(
            source,
            outline,
            contract,
            context,
            polish_draft,
        )
        return self.gate(source, outline, contract, candidate, context)

    def gate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        context: str | None = None,
    ) -> GenerationOutcome:
        """Repair and evaluate an existing candidate without committing it."""
        source = story.generation_view(candidate.index)
        evaluation_context = context or self.context.build(candidate.index, source)
        working_candidate = candidate.model_copy(deep=True)
        assessments: list[ChapterAssessment] = []

        for attempt in range(1, self.evaluator.policy.max_repairs + 2):
            assessment = self.evaluator.evaluate(
                source,
                outline,
                contract,
                working_candidate,
                evaluation_context,
                attempt,
            )
            assessments.append(assessment)
            if assessment.decision is GenerationDecision.ACCEPT:
                return GenerationOutcome(working_candidate, True, tuple(assessments))
            if assessment.decision is GenerationDecision.REJECT:
                break
            revised = self.editor.revise_from_quality_report(
                working_candidate.content,
                assessment.quality,
                story.style_guide,
            ).strip()
            if not revised or revised == working_candidate.content.strip():
                assessments[-1] = replace(
                    assessment,
                    decision=GenerationDecision.REJECT,
                    reasons=(*assessment.reasons, "repair:empty_or_unchanged"),
                )
                break
            working_candidate.content = revised

        return GenerationOutcome(working_candidate, False, tuple(assessments))


__all__ = [
    "CandidateEvaluator",
    "ChapterAssessment",
    "ChapterGenerationPipeline",
    "GenerationOutcome",
    "GenerationPolicy",
]
