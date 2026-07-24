"""Reliable chapter generation as explicit candidate, gate, repair, and decision stages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Callable, Protocol

from novelforge.core.generation_budget import (
    GenerationBudget,
    GenerationBudgetExceeded,
    current_generation_budget,
    generation_budget_scope,
)
from novelforge.domain import (
    Chapter,
    ChapterContract,
    ChapterGenerationReport,
    ChapterOutline,
    ConstraintCheck,
    ContinuityAuditReport,
    ContractEvidenceLedger,
    ContractExecutionPlan,
    ContractReviewEvidence,
    GenerationAttemptReport,
    GenerationBudgetReport,
    GenerationDecision,
    QualityReviewReport,
    RevisionIssue,
    SceneCandidateSelection,
    ScenePatch,
    Story,
    content_digest,
)
from novelforge.validation import ContractObligationCompiler


@dataclass(frozen=True)
class GenerationPolicy:
    min_quality_score: float = 7.5
    max_repairs: int = 2
    blocking_severities: frozenset[str] = frozenset({"high", "critical"})
    require_contract_pass: bool = True
    require_continuity_pass: bool = True
    auto_repair_review_issues: bool = True
    max_generation_calls: int = 16
    max_generation_tokens: int = 42_000
    quality_search_enabled: bool = True
    quality_search_max_scenes: int = 1
    quality_search_candidates: int = 2


@dataclass(frozen=True)
class ChapterAssessment:
    attempt: int
    contract_checks: tuple[ConstraintCheck, ...]
    continuity: ContinuityAuditReport
    quality: QualityReviewReport
    score: float
    decision: GenerationDecision
    reasons: tuple[str, ...] = ()
    execution_plan: ContractExecutionPlan | None = None
    evidence_ledger: ContractEvidenceLedger | None = None
    review_mode: str = "full"
    repair_obligation_ids: tuple[str, ...] = ()
    changed_scene_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class GenerationOutcome:
    candidate: Chapter
    accepted: bool
    assessments: tuple[ChapterAssessment, ...] = ()
    candidate_selections: tuple[SceneCandidateSelection, ...] = ()
    budget: GenerationBudgetReport | None = None

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
                    execution_plan=item.execution_plan,
                    evidence_ledger=item.evidence_ledger,
                    review_mode=item.review_mode,
                    repair_obligation_ids=list(item.repair_obligation_ids),
                    changed_scene_indexes=list(item.changed_scene_indexes),
                )
                for item in self.assessments
            ],
            candidate_selections=list(self.candidate_selections),
            budget=self.budget,
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
        obligations: ContractObligationCompiler | None = None,
    ) -> None:
        self.contracts = contracts
        self.continuity = continuity
        self.critic = critic
        self.policy = policy
        self.obligations = obligations or ContractObligationCompiler()
        self._review_cache: dict[
            tuple[str, int, str],
            tuple[
                ContinuityAuditReport,
                QualityReviewReport,
                tuple[ContractReviewEvidence, ...],
            ],
        ] = {}

    def evaluate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        context: str,
        attempt: int,
    ) -> ChapterAssessment:
        plan, checks, ledger, _ = self.hard_contract_gate(contract, candidate)
        conflict_checks = self.obligations.conflict_checks(plan)
        uses_fast_validation = callable(getattr(self.contracts, "validate_fast", None))
        cache_key = (str(story.id), story.revision, candidate.content)
        pre_review_failures = [
            check
            for check in checks
            if (
                self._is_definite_contract_failure(check, defer_to_unified=uses_fast_validation)
                if uses_fast_validation
                else self._is_blocking_contract_failure(check)
            )
        ]
        failed_contract = pre_review_failures
        if pre_review_failures:
            review_mode = "contract_only"
            continuity = ContinuityAuditReport(
                chapter_index=candidate.index,
                passed=True,
                summary="Deferred until hard contract obligations are repaired.",
                audit_method="deferred_contract_failure",
            )
            quality = QualityReviewReport(
                overall_comment="Deferred full review until hard contract obligations are repaired.",
            )
        elif cache_key in self._review_cache:
            review_mode = "cache"
            cached_continuity, cached_quality, cached_evidence = self._review_cache[cache_key]
            continuity = cached_continuity.model_copy(deep=True)
            quality = cached_quality.model_copy(deep=True)
            self._apply_contract_evidence(checks, plan, cached_evidence)
            ledger = self.obligations.build_ledger(plan, checks, candidate.beats)
            failed_contract = [
                check for check in checks if self._is_blocking_contract_failure(check)
            ]
        else:
            review_context = self._review_context(context, plan, ledger)
            unified = self._unified_review(candidate, outline, story, review_context)
            if unified is not None:
                review_mode = "unified"
                continuity, quality, contract_evidence = unified
                self._apply_contract_evidence(checks, plan, contract_evidence)
                ledger = self.obligations.build_ledger(plan, checks, candidate.beats)
                failed_contract = [
                    check for check in checks if self._is_blocking_contract_failure(check)
                ]
            else:
                review_mode = "split_fallback"
                checks = [*conflict_checks, *self.contracts.validate(candidate.content, contract)]
                if candidate.beats and not candidate.scene_content_is_current():
                    checks.append(self._scene_sync_check(candidate))
                ledger = self.obligations.build_ledger(plan, checks, candidate.beats)
                failed_contract = [
                    check for check in checks if self._is_blocking_contract_failure(check)
                ]
                if failed_contract:
                    continuity = ContinuityAuditReport(
                        chapter_index=candidate.index,
                        passed=True,
                        summary="Deferred until hard contract obligations are repaired.",
                        audit_method="deferred_contract_failure",
                    )
                    quality = QualityReviewReport(
                        overall_comment="Deferred full review until hard contract obligations are repaired.",
                    )
                else:
                    continuity = self.continuity.audit_chapter(
                        story,
                        candidate.index,
                        candidate.content,
                        review_context,
                    )
                    quality = self.critic.review_quality_scorecard(
                        candidate.content,
                        outline,
                        story,
                        extra_context=review_context,
                    )
                contract_evidence = ()
            self._review_cache[cache_key] = (
                continuity.model_copy(deep=True),
                quality.model_copy(deep=True),
                tuple(contract_evidence),
            )
        repair_obligation_ids = tuple(
            entry.obligation_id
            for entry in ledger.entries
            if any(
                entry.constraint_type == check.constraint_type
                and entry.requirement == check.requirement
                for check in failed_contract
            )
        )
        quality.contract_checks = checks

        reasons: list[str] = []
        if self.policy.require_contract_pass and failed_contract:
            reasons.extend(f"contract:{check.constraint_type}" for check in failed_contract)
            quality.hard_constraints_passed = False
            quality.issues.extend(self._contract_issues(failed_contract))

        blocking_continuity = [
            issue
            for issue in continuity.issues
            if str(issue.severity) in self.policy.blocking_severities
        ]
        # A bare model boolean is not actionable enough to justify rewriting a
        # contract-compliant chapter. Automatic repair needs a cited high-risk
        # issue; otherwise preserve the draft and retain the audit in its report.
        if self.policy.require_continuity_pass and blocking_continuity:
            reasons.extend(f"continuity:{issue.dimension}" for issue in blocking_continuity)
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

        contract_blocked = bool(failed_contract)
        score_blocked = score < self.policy.min_quality_score
        continuity_blocked = bool(blocking_continuity)
        if not reasons or (
            not contract_blocked
            and not score_blocked
            and not continuity_blocked
            and not self.policy.auto_repair_review_issues
        ):
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
            execution_plan=plan,
            evidence_ledger=ledger,
            review_mode=review_mode,
            repair_obligation_ids=repair_obligation_ids,
        )

    def hard_contract_gate(
        self,
        contract: ChapterContract,
        candidate: Chapter,
    ) -> tuple[
        ContractExecutionPlan,
        list[ConstraintCheck],
        ContractEvidenceLedger,
        list[ConstraintCheck],
    ]:
        """Run the non-negotiable gate used before any quality comparison."""
        plan = self.obligations.compile(contract, candidate.beats)
        checks = [
            *self.obligations.conflict_checks(plan),
            *self._fast_contract_checks(candidate.content, contract),
        ]
        if candidate.beats and not candidate.scene_content_is_current():
            checks.append(self._scene_sync_check(candidate))
        ledger = self.obligations.build_ledger(plan, checks, candidate.beats)
        failed = [item for item in checks if self._is_blocking_contract_failure(item)]
        return plan, checks, ledger, failed

    @staticmethod
    def _scene_sync_check(candidate: Chapter) -> ConstraintCheck:
        return ConstraintCheck(
            constraint_type="scene_patch_sync",
            requirement="chapter.content must equal the merge of every scene patch source",
            passed=False,
            severity="critical",
            status="failed",
            message="Chapter prose is stale relative to scene content; apply a ScenePatch before review.",
            validation_method="scene_patch_invariant",
        )

    def evaluate_incremental_contract(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        prior: ChapterAssessment,
        context: str,
        attempt: int,
        changed_scene_indexes: tuple[int, ...] = (),
    ) -> ChapterAssessment:
        """Compatibility entry point for the v0.4 patch-local evaluation path."""
        return self.evaluate_local_patch(
            story,
            outline,
            contract,
            candidate,
            prior,
            context,
            attempt,
            changed_scene_indexes=changed_scene_indexes,
        )

    def evaluate_local_patch(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        prior: ChapterAssessment,
        context: str,
        attempt: int,
        *,
        changed_scene_indexes: tuple[int, ...] = (),
    ) -> ChapterAssessment:
        """Revalidate a scene patch, its hard contract, and its local hand-offs."""
        # A pre-review deterministic failure has no reusable craft score. Once
        # its repair clears the contract, establish a full baseline first.
        if prior.review_mode == "contract_only":
            baseline = self.evaluate(story, outline, contract, candidate, context, attempt)
            if not changed_scene_indexes or baseline.decision is not GenerationDecision.ACCEPT:
                return baseline
            prior = baseline

        plan, checks, ledger, failed_contract = self.hard_contract_gate(contract, candidate)
        repair_obligation_ids = tuple(
            entry.obligation_id
            for entry in ledger.entries
            if any(
                entry.constraint_type == check.constraint_type
                and entry.requirement == check.requirement
                for check in failed_contract
            )
        )

        quality = prior.quality.model_copy(deep=True)
        quality.contract_checks = checks
        quality.hard_constraints_passed = not failed_contract
        quality.issues = [
            issue for issue in quality.issues if not self._is_contract_derived_issue(issue.dimension)
        ]
        continuity = self._local_continuity_audit(
            story,
            candidate,
            changed_scene_indexes,
            context,
            fallback=prior.continuity,
        )

        reasons: list[str] = []
        if self.policy.require_contract_pass and failed_contract:
            reasons.extend(f"contract:{check.constraint_type}" for check in failed_contract)
            quality.issues.extend(self._contract_issues(failed_contract))
        blocking_continuity = [
            issue
            for issue in continuity.issues
            if str(issue.severity) in self.policy.blocking_severities
        ]
        if self.policy.require_continuity_pass and blocking_continuity:
            reasons.extend(f"continuity:{issue.dimension}" for issue in blocking_continuity)
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

        contract_blocked = bool(failed_contract)
        score_blocked = score < self.policy.min_quality_score
        continuity_blocked = bool(blocking_continuity)
        if not reasons or (
            not contract_blocked
            and not score_blocked
            and not continuity_blocked
            and not self.policy.auto_repair_review_issues
        ):
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
            execution_plan=plan,
            evidence_ledger=ledger,
            review_mode="incremental_contract",
            repair_obligation_ids=repair_obligation_ids,
            changed_scene_indexes=changed_scene_indexes,
        )

    def _local_continuity_audit(
        self,
        story: Story,
        candidate: Chapter,
        changed_scene_indexes: tuple[int, ...],
        context: str,
        *,
        fallback: ContinuityAuditReport,
    ) -> ContinuityAuditReport:
        """Audit mutation boundaries, with a full-audit fallback for older ports."""
        if not changed_scene_indexes:
            return fallback.model_copy(deep=True)
        local = getattr(self.continuity, "audit_local_patch", None)
        if callable(local):
            return local(story, candidate, list(changed_scene_indexes), context)
        return self.continuity.audit_chapter(
            story,
            candidate.index,
            candidate.content,
            f"local_patch_scenes={list(changed_scene_indexes)}\n{context}",
        )

    @staticmethod
    def _is_contract_derived_issue(dimension: str) -> bool:
        normalized = dimension.lower()
        return (
            normalized.startswith("contract:")
            or "contract_obligation" in normalized
            or "knowledge_boundary" in normalized
            or "knowledge_acquisition" in normalized
        )

    @staticmethod
    def _is_blocking_contract_failure(check: ConstraintCheck) -> bool:
        """Separate real violations from evidence-only uncertainty and soft preferences."""
        if check.constraint_type in {"contract_conflict", "scene_patch_sync"}:
            return True
        if check.constraint_type in {"must_happen", "ending_hook"}:
            return not check.passed
        if check.constraint_type in {"must_not_happen", "knowledge_boundary", "knowledge_acquisition"}:
            return check.status == "failed"
        return False

    @staticmethod
    def _is_definite_contract_failure(
        check: ConstraintCheck,
        *,
        defer_to_unified: bool = False,
    ) -> bool:
        """Failures that cannot be resolved by semantic review of an omission."""
        if check.constraint_type == "contract_conflict":
            return True
        if defer_to_unified:
            # The unified review receives the deterministic evidence packet and
            # can distinguish an actual prohibited event from an order, threat,
            # refusal, or incomplete action. This avoids spending a repair on
            # a lexical false positive before the reviewer has seen context.
            return False
        return check.constraint_type in {
            "must_not_happen",
            "knowledge_boundary",
            "knowledge_acquisition",
        } and check.status == "failed"

    def _fast_contract_checks(
        self,
        content: str,
        contract: ChapterContract,
    ) -> list[ConstraintCheck]:
        fast_validate = getattr(self.contracts, "validate_fast", None)
        if callable(fast_validate):
            return fast_validate(content, contract)
        return self.contracts.validate(content, contract)

    @staticmethod
    def _apply_contract_evidence(
        checks: list[ConstraintCheck],
        plan: ContractExecutionPlan,
        evidence_items: tuple[ContractReviewEvidence, ...],
    ) -> None:
        """Promote cited unified-review verdicts into the traceable contract checks."""
        obligations = {item.id: item for item in plan.obligations}
        by_requirement = {
            (check.constraint_type, check.requirement): check for check in checks
        }
        for evidence in evidence_items:
            obligation = obligations.get(evidence.obligation_id)
            if obligation is None or evidence.confidence < 0.7:
                continue
            if not evidence.evidence.strip() or not evidence.paragraph_range.strip():
                continue
            check = by_requirement.get((obligation.constraint_type, obligation.requirement))
            if check is None:
                continue
            if (
                check.constraint_type
                in {"must_not_happen", "knowledge_boundary", "knowledge_acquisition"}
                and check.rule_passed is False
            ):
                # A deterministic violation with a span is authoritative. The
                # reviewer may add explanation but cannot erase that evidence.
                continue
            check.semantic_passed = evidence.passed
            check.confidence = evidence.confidence
            check.evidence = evidence.evidence[:300]
            check.paragraph_range = evidence.paragraph_range[:80]
            check.validation_method = "rule+unified"
            check.passed = evidence.passed
            check.status = "passed" if evidence.passed else "failed"

    @staticmethod
    def _review_context(
        context: str,
        plan: ContractExecutionPlan,
        ledger: ContractEvidenceLedger,
    ) -> str:
        """Share one compact contract packet across quality and continuity review prompts."""
        obligations = []
        semantic_exception_ids = {
            entry.obligation_id
            for entry in ledger.entries
            if not entry.passed
            and entry.constraint_type in {"must_not_happen", "knowledge_boundary"}
        }
        seen_requirements: set[tuple[str, str]] = set()
        for item in plan.obligations:
            key = (item.constraint_type, item.requirement)
            if key in seen_requirements:
                continue
            # Deterministic validation already owns the exhaustive global
            # exclusion checks. Sending every repeated must-not obligation to
            # the semantic reviewer makes its JSON response grow with the
            # number of scenes without adding a new decision. Keep the shared
            # review packet for obligations that need positive prose evidence
            # or a semantic interpretation of a rule miss.
            if (
                item.constraint_type
                in {"must_not_happen", "knowledge_boundary", "knowledge_acquisition"}
                and item.id not in semantic_exception_ids
            ):
                continue
            seen_requirements.add(key)
            obligations.append(
                {
                    "id": item.id,
                    "scene": item.scene_index,
                    "type": item.constraint_type,
                    "requirement": item.requirement,
                }
            )
        evidence = [
            {
                "id": item.obligation_id,
                "scene": item.scene_index,
                "passed": item.passed,
                "evidence": item.evidence,
            }
            for item in ledger.entries
            if (
                item.constraint_type
                not in {"must_not_happen", "knowledge_boundary", "knowledge_acquisition"}
                or item.obligation_id in semantic_exception_ids
            )
        ]
        return (
            f"shared_contract_obligations={obligations}\n"
            f"shared_contract_evidence={evidence}\n"
            f"retrieval_context={context[:3500]}"
        )

    def _unified_review(
        self,
        candidate: Chapter,
        outline: ChapterOutline,
        story: Story,
        context: str,
    ) -> tuple[ContinuityAuditReport, QualityReviewReport, tuple[ContractReviewEvidence, ...]] | None:
        review = getattr(self.critic, "review_generation_bundle", None)
        if not callable(review):
            return None
        bundle = review(candidate.content, outline, story, context)
        if bundle is None:
            return None
        return bundle.continuity, bundle.quality, tuple(bundle.contract_evidence)

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
        budget = GenerationBudget(
            max_calls=self.evaluator.policy.max_generation_calls,
            max_tokens=self.evaluator.policy.max_generation_tokens,
        )
        candidate = Chapter(index=outline.chapter_index, title=outline.title)
        with generation_budget_scope(budget):
            try:
                candidate = self.composer.compose(
                    source,
                    outline,
                    contract,
                    context,
                    polish_draft,
                )
                outcome = self._gate(source, outline, contract, candidate, context)
            except GenerationBudgetExceeded:
                outcome = self._budget_rejected(candidate, ())
        return replace(outcome, budget=self._budget_report(budget))

    def gate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        context: str | None = None,
    ) -> GenerationOutcome:
        """Repair and evaluate an existing candidate without committing it."""
        active_budget = current_generation_budget()
        if active_budget is not None:
            return self._gate(story, outline, contract, candidate, context)
        budget = GenerationBudget(
            max_calls=self.evaluator.policy.max_generation_calls,
            max_tokens=self.evaluator.policy.max_generation_tokens,
        )
        with generation_budget_scope(budget):
            try:
                outcome = self._gate(story, outline, contract, candidate, context)
            except GenerationBudgetExceeded:
                outcome = self._budget_rejected(candidate, ())
        return replace(outcome, budget=self._budget_report(budget))

    def _gate(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        context: str | None = None,
    ) -> GenerationOutcome:
        """Budget-scoped candidate gate used by generate() and direct revision paths."""
        source = story.generation_view(candidate.index)
        evaluation_context = context or self.context.build(candidate.index, source)
        working_candidate = candidate.model_copy(deep=True)
        assessments: list[ChapterAssessment] = []
        selections: list[SceneCandidateSelection] = []
        incremental_prior: ChapterAssessment | None = None
        incremental_changed: tuple[int, ...] = ()
        search_attempted = False

        try:
            for attempt in range(1, self.evaluator.policy.max_repairs + 2):
                if incremental_prior is not None:
                    assessment = self.evaluator.evaluate_incremental_contract(
                        source,
                        outline,
                        contract,
                        working_candidate,
                        incremental_prior,
                        evaluation_context,
                        attempt,
                        changed_scene_indexes=incremental_changed,
                    )
                    incremental_prior = None
                    incremental_changed = ()
                else:
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
                    if not search_attempted:
                        search_attempted = True
                        searched, new_selections, changed = self._quality_search(
                            source,
                            outline,
                            contract,
                            working_candidate,
                            assessment,
                            evaluation_context,
                        )
                        selections.extend(new_selections)
                        if searched is not None and changed:
                            working_candidate = searched
                            local = self.evaluator.evaluate_local_patch(
                                source,
                                outline,
                                contract,
                                working_candidate,
                                assessment,
                                evaluation_context,
                                attempt,
                                changed_scene_indexes=changed,
                            )
                            assessments.append(local)
                            if local.decision is GenerationDecision.ACCEPT:
                                return GenerationOutcome(
                                    working_candidate,
                                    True,
                                    tuple(assessments),
                                    tuple(selections),
                                )
                            assessment = local
                        else:
                            return GenerationOutcome(
                                working_candidate,
                                True,
                                tuple(assessments),
                                tuple(selections),
                            )
                    else:
                        return GenerationOutcome(
                            working_candidate,
                            True,
                            tuple(assessments),
                            tuple(selections),
                        )
                if assessment.decision is GenerationDecision.REJECT:
                    break
                targeted = self._targeted_contract_repair(source, working_candidate, assessment)
                if targeted is not None:
                    incremental_changed = self._changed_scene_indexes(working_candidate, targeted)
                    working_candidate = targeted
                    incremental_prior = assessment
                    continue
                revised, changed = self._quality_scene_repair(
                    working_candidate,
                    assessment,
                    story.style_guide,
                )
                if revised is None or (working_candidate.beats and not changed):
                    assessments[-1] = replace(
                        assessment,
                        decision=GenerationDecision.REJECT,
                        reasons=(*assessment.reasons, "repair:empty_or_unchanged"),
                    )
                    break
                working_candidate = revised
                incremental_prior = assessment if changed else None
                incremental_changed = changed
        except GenerationBudgetExceeded:
            return self._budget_rejected(working_candidate, tuple(assessments), tuple(selections))

        return GenerationOutcome(working_candidate, False, tuple(assessments), tuple(selections))

    def _targeted_contract_repair(
        self,
        story: Story,
        candidate: Chapter,
        assessment: ChapterAssessment,
    ) -> Chapter | None:
        ledger = assessment.evidence_ledger
        repair = getattr(self.composer, "repair_contract_failures", None)
        if not ledger or not assessment.repair_obligation_ids or not callable(repair):
            return None
        scoped_ledger = ledger.model_copy(deep=True)
        scoped_ledger.entries = [
            entry for entry in scoped_ledger.entries if entry.obligation_id in assessment.repair_obligation_ids
        ]
        if not scoped_ledger.failed_entries:
            return None
        revised = repair(story, candidate, scoped_ledger)
        if revised.content.strip() == candidate.content.strip():
            return None
        return revised

    def apply_scene_patches(self, candidate: Chapter, patches: list[ScenePatch]) -> Chapter:
        """Normalize patch provenance and apply a reusable scene-edit transaction."""
        if not patches:
            return candidate
        source_by_scene = {item.scene_index: item.content for item in candidate.beats}
        normalized = [
            patch.model_copy(
                update={"source_content_digest": content_digest(source_by_scene[patch.scene_index])}
            )
            for patch in patches
            if patch.scene_index in source_by_scene
        ]
        if not normalized:
            return candidate
        apply_patches = getattr(self.composer, "apply_scene_patches", None)
        if callable(apply_patches):
            return apply_patches(candidate, normalized)
        working = candidate.model_copy(deep=True)
        working.apply_scene_patches(normalized)
        return working

    def _quality_scene_repair(
        self,
        candidate: Chapter,
        assessment: ChapterAssessment,
        style_guide: str,
    ) -> tuple[Chapter | None, tuple[int, ...]]:
        """Repair cited quality defects as scene patches, never as a chapter string."""
        revise = getattr(self.editor, "revise_scenes_from_quality_report", None)
        apply_patches = getattr(self.composer, "apply_scene_patches", None)
        if candidate.beats and callable(revise) and callable(apply_patches):
            scene_indexes = self._risk_scene_indexes(candidate, assessment)
            scenes = [item for item in candidate.beats if item.scene_index in scene_indexes]
            patches = revise(scenes, assessment.quality, style_guide)
            if not patches:
                return None, ()
            revised = self.apply_scene_patches(candidate, patches)
            changed = self._changed_scene_indexes(candidate, revised)
            return (revised, changed) if changed else (None, ())

        # Compatibility bridge for pre-v0.4 custom composers that do not expose
        # scenes. Product generation always takes the ScenePatch path above.
        if candidate.beats:
            return None, ()
        revised = self.editor.revise_from_quality_report(
            candidate.content, assessment.quality, style_guide
        ).strip()
        if not revised or revised == candidate.content.strip():
            return None, ()
        return candidate.model_copy(update={"content": revised}), ()

    def _quality_search(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        assessment: ChapterAssessment,
        context: str,
    ) -> tuple[Chapter | None, list[SceneCandidateSelection], tuple[int, ...]]:
        """Search only risk-ranked scenes: hard gate first, blind selector second."""
        policy = self.evaluator.policy
        generate = getattr(self.composer, "generate_scene_quality_patches", None)
        apply_patches = getattr(self.composer, "apply_scene_patches", None)
        choose = getattr(self.evaluator.critic, "select_scene_candidate", None)
        if (
            not policy.quality_search_enabled
            or policy.quality_search_max_scenes <= 0
            or not candidate.beats
            or not callable(generate)
            or not callable(apply_patches)
            or not callable(choose)
        ):
            return None, [], ()
        scene_indexes = self._risk_scene_indexes(candidate, assessment)
        alternate_count = max(0, policy.quality_search_candidates - 1)
        if not scene_indexes or alternate_count < 1:
            return None, [], ()
        budget = current_generation_budget()
        # Every alternate needs one expressive draft and an evidence-backed
        # semantic hard gate. Each risk scene then needs an independent choice,
        # followed by one mandatory local continuity audit for the selected
        # patch set. Search is optional, so lack of budget preserves an already
        # accepted chapter rather than causing a rejection.
        minimum_calls = len(scene_indexes) * (alternate_count * 2 + 1) + 1
        if (
            budget is not None
            and budget.remaining_calls is not None
            and budget.remaining_calls < minimum_calls
        ):
            return None, [], ()
        _, base_checks, _, _ = self.evaluator.hard_contract_gate(contract, candidate)
        if any(
            self.evaluator._is_definite_contract_failure(check, defer_to_unified=True)
            for check in base_checks
        ):
            return None, [], ()
        try:
            alternatives = generate(
                story,
                outline,
                contract,
                candidate,
                list(scene_indexes),
                variants_per_scene=policy.quality_search_candidates,
            )
        except GenerationBudgetExceeded:
            return None, [], ()
        working = candidate
        selections: list[SceneCandidateSelection] = []
        changed: list[int] = []
        for scene_index in scene_indexes:
            scene = next((item for item in working.beats if item.scene_index == scene_index), None)
            patches = alternatives.get(scene_index, [])
            if scene is None or not patches:
                continue
            original_id = self._candidate_id(scene.content)
            viable: dict[str, tuple[str, ScenePatch | None, Chapter]] = {
                original_id: (scene.content, None, working)
            }
            for patch in patches:
                try:
                    alternative = apply_patches(working, [patch])
                except Exception:
                    continue
                try:
                    failures = self._semantic_hard_gate(contract, alternative)
                except GenerationBudgetExceeded:
                    return None, [], ()
                if failures:
                    continue
                candidate_scene = next(
                    item for item in alternative.beats if item.scene_index == scene_index
                )
                candidate_id = self._candidate_id(candidate_scene.content)
                viable[candidate_id] = (candidate_scene.content, patch, alternative)
            if len(viable) < 2:
                continue
            selection = choose(
                scene=scene,
                candidates={key: item[0] for key, item in viable.items()},
                style_guide=story.style_guide,
                context=context,
            )
            if selection is None or selection.selected_id not in viable:
                continue
            selections.append(selection)
            _, selected_patch, selected_candidate = viable[selection.selected_id]
            if selected_patch is not None:
                working = selected_candidate
                changed.append(scene_index)
        return (working if changed else None), selections, tuple(sorted(set(changed)))

    def _semantic_hard_gate(
        self,
        contract: ChapterContract,
        candidate: Chapter,
    ) -> list[ConstraintCheck]:
        """Gate an alternate with deterministic and cited semantic evidence.

        Exact phrase matching is not enough for Chinese prose: a
        contract-compliant paraphrase may not reuse an obligation's original
        wording. Structural violations are rejected immediately; otherwise the
        validator must provide an evidence-backed semantic decision before the
        independent quality selector can see the alternative.
        """
        _, static_checks, _, _ = self.evaluator.hard_contract_gate(contract, candidate)
        definite_failures = [
            check
            for check in static_checks
            if self.evaluator._is_definite_contract_failure(check, defer_to_unified=True)
        ]
        if definite_failures:
            return definite_failures
        semantic_checks = self.evaluator.contracts.validate(candidate.content, contract)
        return [
            check
            for check in semantic_checks
            if self.evaluator._is_blocking_contract_failure(check)
        ]

    def _risk_scene_indexes(
        self,
        candidate: Chapter,
        assessment: ChapterAssessment,
    ) -> tuple[int, ...]:
        """Rank only scenes whose contract density or cited issue makes them risky."""
        scores: dict[int, int] = {}
        ordered = sorted(candidate.beats, key=lambda item: item.scene_index)
        for scene in ordered:
            score = 0
            for obligation in scene.contract_obligations:
                mode = str(obligation.get("mode", ""))
                score += 3 if mode in {"must_end_with", "must_show_source"} else 1
            if scene is ordered[-1]:
                score += 3
            for issue in assessment.quality.issues:
                if issue.evidence and issue.evidence in scene.content:
                    score += 4 if str(issue.severity) in {"high", "critical"} else 2
            scores[scene.scene_index] = score
        ranked = sorted(scores, key=lambda index: (-scores[index], index))
        return tuple(ranked[: self.evaluator.policy.quality_search_max_scenes])

    @staticmethod
    def _candidate_id(content: str) -> str:
        return f"scene-{sha256(content.encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _changed_scene_indexes(before: Chapter, after: Chapter) -> tuple[int, ...]:
        old = {item.scene_index: item for item in before.beats}
        changed = [
            item.scene_index
            for item in after.beats
            if item.scene_index not in old
            or item.content != old[item.scene_index].content
            or item.end_state != old[item.scene_index].end_state
        ]
        return tuple(sorted(changed))

    @staticmethod
    def _budget_report(budget: GenerationBudget) -> GenerationBudgetReport:
        return GenerationBudgetReport(
            max_calls=budget.max_calls,
            max_tokens=budget.max_tokens,
            calls_used=budget.calls_used,
            tokens_used=budget.tokens_used,
            estimated_tokens_used=budget.estimated_tokens_used,
            exhausted_reason=budget.exhausted_reason,
            operations=list(budget.operations),
        )

    @staticmethod
    def _budget_rejected(
        candidate: Chapter,
        assessments: tuple[ChapterAssessment, ...],
        selections: tuple[SceneCandidateSelection, ...] = (),
    ) -> GenerationOutcome:
        if assessments:
            final = replace(
                assessments[-1],
                decision=GenerationDecision.REJECT,
                reasons=(*assessments[-1].reasons, "budget:exhausted"),
            )
            return GenerationOutcome(candidate, False, (*assessments[:-1], final), selections)
        assessment = ChapterAssessment(
            attempt=1,
            contract_checks=(),
            continuity=ContinuityAuditReport(
                chapter_index=candidate.index,
                passed=False,
                summary="Generation budget exhausted before a complete assessment.",
                audit_method="budget_guard",
            ),
            quality=QualityReviewReport(
                overall_comment="Generation budget exhausted before a complete assessment."
            ),
            score=0.0,
            decision=GenerationDecision.REJECT,
            reasons=("budget:exhausted",),
            review_mode="budget_guard",
        )
        return GenerationOutcome(candidate, False, (assessment,), selections)


__all__ = [
    "CandidateEvaluator",
    "ChapterAssessment",
    "ChapterGenerationPipeline",
    "GenerationOutcome",
    "GenerationPolicy",
]
