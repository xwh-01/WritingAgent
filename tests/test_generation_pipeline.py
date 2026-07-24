from __future__ import annotations

import re

from novelforge.application.generation import (
    CandidateEvaluator,
    ChapterGenerationPipeline,
    GenerationPolicy,
)
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    CheckStatus,
    ConstraintCheck,
    ContinuityAuditReport,
    GenerationDecision,
    QualityReviewReport,
    QualityScores,
    RevisionIssue,
    UnifiedReviewBundle,
)


class Composer:
    def compose(self, story, outline, contract, context, polish_draft):
        return Chapter(index=outline.chapter_index, title=outline.title, content="weak draft")


class Context:
    def build(self, chapter_index, story):
        return "history before target"


class Contracts:
    def validate(self, content, contract):
        return []


class Continuity:
    def audit_chapter(self, story, chapter_index, content, context):
        return ContinuityAuditReport(chapter_index=chapter_index, passed=True)


class Critic:
    def review_quality_scorecard(self, content, outline, story, extra_context=""):
        score = 9.0 if content == "fixed draft" else 5.0
        return QualityReviewReport(
            scores=QualityScores(
                logic_consistency=score,
                character_fidelity=score,
                foreshadowing_handling=score,
                pacing=score,
                style_uniformity=score,
            )
        )


class Editor:
    def __init__(self, replacement: str) -> None:
        self.replacement = replacement

    def revise_from_quality_report(self, content, report, style_guide=""):
        return self.replacement


def pipeline(editor: Editor) -> ChapterGenerationPipeline:
    return ChapterGenerationPipeline(
        composer=Composer(),
        context=Context(),
        evaluator=CandidateEvaluator(
            contracts=Contracts(),
            continuity=Continuity(),
            critic=Critic(),
            policy=GenerationPolicy(min_quality_score=7.5, max_repairs=2),
        ),
        editor=editor,
    )


def test_pipeline_repairs_then_accepts_without_mutating_story(planned_story) -> None:
    original = planned_story.model_dump_json()
    outcome = pipeline(Editor("fixed draft")).generate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        lambda story, chapter, content: content,
    )

    assert outcome.accepted is True
    assert [item.decision for item in outcome.assessments] == [
        GenerationDecision.REPAIR,
        GenerationDecision.ACCEPT,
    ]
    assert outcome.candidate.content == "fixed draft"
    assert planned_story.model_dump_json() == original


def test_pipeline_marks_unrepairable_candidate_rejected(planned_story) -> None:
    outcome = pipeline(Editor("weak draft")).generate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        lambda story, chapter, content: content,
    )

    assert outcome.accepted is False
    assert outcome.final_assessment.decision is GenerationDecision.REJECT
    assert "repair:empty_or_unchanged" in outcome.final_assessment.reasons
    assert planned_story.manuscript.chapters == {}


class TargetedComposer:
    def __init__(self) -> None:
        self.targeted_repairs = 0

    def compose(self, story, outline, contract, context, polish_draft):
        first = Beat(
            scene_index=1,
            title="缺失事件",
            purpose="推进冲突",
            goal="完成合同事件",
            outcome="事件完成",
            character_goals={"主角": "完成事件"},
            must_happen=[contract.must_happen[0]],
            content="坏场景",
        )
        second = Beat(
            scene_index=2,
            title="不应改动",
            purpose="保留后果",
            goal="承接前场",
            outcome="状态变化",
            character_goals={"主角": "承接"},
            content="不相关场景",
        )
        return Chapter(
            index=outline.chapter_index,
            title=outline.title,
            beats=[first, second],
            content="坏场景\n\n***\n\n不相关场景",
        )

    def repair_contract_failures(self, story, candidate, ledger):
        self.targeted_repairs += 1
        repaired = candidate.model_copy(deep=True)
        repaired.beats[0].content = "合同事件已完成"
        repaired.content = "合同事件已完成\n\n***\n\n不相关场景"
        return repaired


class TargetedContracts:
    def validate(self, content, contract):
        if "合同事件已完成" in content:
            return []
        return [
            ConstraintCheck(
                constraint_type="must_happen",
                requirement=contract.must_happen[0],
                passed=False,
                status=CheckStatus.FAILED,
                message="合同事件缺失",
            )
        ]


class TargetedCritic:
    def review_quality_scorecard(self, content, outline, story, extra_context=""):
        return QualityReviewReport(
            scores=QualityScores(
                logic_consistency=9,
                character_fidelity=9,
                foreshadowing_handling=9,
                pacing=9,
                style_uniformity=9,
            )
        )


def test_pipeline_repairs_only_failed_scenes_when_evidence_ledger_has_a_target(planned_story) -> None:
    composer = TargetedComposer()
    target_contract = planned_story.design.chapter_contracts[1].model_copy(deep=True)
    target_contract.must_happen = ["合同事件已完成"]
    pipeline = ChapterGenerationPipeline(
        composer=composer,
        context=Context(),
        evaluator=CandidateEvaluator(
            contracts=TargetedContracts(),
            continuity=Continuity(),
            critic=TargetedCritic(),
            policy=GenerationPolicy(min_quality_score=7.5, max_repairs=1),
        ),
        editor=Editor("不应触发全文重写"),
    )

    outcome = pipeline.generate(
        planned_story,
        planned_story.get_outline(1),
        target_contract,
        lambda story, chapter, content: content,
    )

    assert outcome.accepted is True
    assert composer.targeted_repairs == 1
    assert outcome.candidate.beats[0].content == "合同事件已完成"
    assert outcome.candidate.beats[1].content == "不相关场景"
    assert outcome.assessments[0].evidence_ledger is not None
    assert outcome.assessments[0].review_mode == "contract_only"
    assert outcome.assessments[0].repair_obligation_ids


def test_pipeline_reuses_the_first_review_after_targeted_contract_repair(planned_story) -> None:
    class FastContracts:
        def validate_fast(self, content, contract):
            if "合同事件已完成" in content:
                return []
            return [
                ConstraintCheck(
                    constraint_type="must_happen",
                    requirement=contract.must_happen[0],
                    passed=False,
                    status=CheckStatus.FAILED,
                    rule_passed=False,
                )
            ]

    class UnifiedCritic:
        def __init__(self) -> None:
            self.calls = 0

        def review_generation_bundle(self, content, outline, story, shared_context=""):
            self.calls += 1
            obligation_id = re.search(r"'id': '([0-9a-f]+)'", shared_context).group(1)
            return UnifiedReviewBundle(
                continuity=ContinuityAuditReport(chapter_index=outline.chapter_index, passed=True),
                quality=QualityReviewReport(
                    scores=QualityScores(
                        logic_consistency=9,
                        character_fidelity=9,
                        foreshadowing_handling=9,
                        pacing=9,
                        style_uniformity=9,
                    )
                ),
                contract_evidence=[
                    {
                        "obligation_id": obligation_id,
                        "passed": False,
                        "confidence": 0.9,
                        "evidence": "坏场景",
                        "paragraph_range": "paragraph 1",
                    }
                ],
            )

    composer = TargetedComposer()
    critic = UnifiedCritic()
    contract = planned_story.design.chapter_contracts[1].model_copy(deep=True)
    contract.must_happen = ["合同事件已完成"]
    outcome = ChapterGenerationPipeline(
        composer=composer,
        context=Context(),
        evaluator=CandidateEvaluator(
            contracts=FastContracts(),
            continuity=Continuity(),
            critic=critic,
            policy=GenerationPolicy(min_quality_score=7.5, max_repairs=1),
        ),
        editor=Editor("不应触发全文重写"),
    ).generate(
        planned_story,
        planned_story.get_outline(1),
        contract,
        lambda story, chapter, content: content,
    )

    assert outcome.accepted is True
    assert critic.calls == 1
    assert [item.review_mode for item in outcome.assessments] == [
        "unified",
        "incremental_contract",
    ]


def test_evaluator_reuses_review_results_for_an_unchanged_candidate(planned_story) -> None:
    class CountingContinuity(Continuity):
        def __init__(self) -> None:
            self.calls = 0

        def audit_chapter(self, story, chapter_index, content, context):
            self.calls += 1
            return super().audit_chapter(story, chapter_index, content, context)

    class CountingCritic(TargetedCritic):
        def __init__(self) -> None:
            self.calls = 0

        def review_quality_scorecard(self, content, outline, story, extra_context=""):
            self.calls += 1
            return super().review_quality_scorecard(content, outline, story, extra_context)

    continuity = CountingContinuity()
    critic = CountingCritic()
    evaluator = CandidateEvaluator(
        contracts=Contracts(),
        continuity=continuity,
        critic=critic,
        policy=GenerationPolicy(min_quality_score=7.5),
    )
    candidate = Chapter(index=1, title="The Choice", content="稳定正文")
    outline = planned_story.get_outline(1)
    contract = ChapterContract(chapter_index=1)

    first = evaluator.evaluate(planned_story, outline, contract, candidate, "shared", 1)
    second = evaluator.evaluate(planned_story, outline, contract, candidate, "shared", 2)

    assert first.decision is GenerationDecision.ACCEPT
    assert second.decision is GenerationDecision.ACCEPT
    assert continuity.calls == 1
    assert critic.calls == 1
    assert second.review_mode == "cache"


def test_unified_review_proves_a_rule_miss_without_second_contract_call(planned_story) -> None:
    class FastContracts:
        def __init__(self) -> None:
            self.semantic_calls = 0

        def validate_fast(self, content, contract):
            return [
                ConstraintCheck(
                    constraint_type="must_happen",
                    requirement="signal arrives",
                    passed=False,
                    status=CheckStatus.FAILED,
                    rule_passed=False,
                )
            ]

        def validate(self, content, contract):
            self.semantic_calls += 1
            raise AssertionError("unified review should replace the semantic contract call")

    class UnifiedCritic:
        def review_generation_bundle(self, content, outline, story, shared_context=""):
            obligation_id = re.search(r"'id': '([0-9a-f]+)'", shared_context).group(1)
            return UnifiedReviewBundle(
                continuity=ContinuityAuditReport(chapter_index=outline.chapter_index, passed=True),
                quality=QualityReviewReport(
                    scores=QualityScores(
                        logic_consistency=9,
                        character_fidelity=9,
                        foreshadowing_handling=9,
                        pacing=9,
                        style_uniformity=9,
                    )
                ),
                contract_evidence=[
                    {
                        "obligation_id": obligation_id,
                        "passed": True,
                        "confidence": 0.9,
                        "evidence": "The signal arrives at the locked door.",
                        "paragraph_range": "paragraph 1",
                    }
                ],
            )

    contracts = FastContracts()
    evaluator = CandidateEvaluator(
        contracts=contracts,
        continuity=Continuity(),
        critic=UnifiedCritic(),
        policy=GenerationPolicy(min_quality_score=7.5),
    )
    contract = ChapterContract(chapter_index=1, must_happen=["signal arrives"])
    candidate = Chapter(
        index=1,
        title="Signal",
        content="The signal arrives at the locked door.",
        beats=[
            Beat(
                scene_index=1,
                purpose="receive signal",
                goal="receive signal",
                outcome="signal arrives",
                character_goals={"hero": "listen"},
                content="The signal arrives at the locked door.",
            )
        ],
    )

    result = evaluator.evaluate(
        planned_story,
        planned_story.get_outline(1),
        contract,
        candidate,
        "shared",
        1,
    )

    assert result.decision is GenerationDecision.ACCEPT
    assert result.review_mode == "unified"
    assert contracts.semantic_calls == 0
    assert result.contract_checks[0].validation_method == "rule+unified"


def test_fast_forbidden_check_is_reviewed_before_targeted_repair(planned_story) -> None:
    class FastContracts:
        def validate_fast(self, content, contract):
            return [
                ConstraintCheck(
                    constraint_type="must_not_happen",
                    requirement="do not reveal the secret",
                    passed=False,
                    status=CheckStatus.FAILED,
                    rule_passed=False,
                    evidence="The guard orders a reveal but no reveal occurs.",
                )
            ]

        def validate(self, content, contract):
            raise AssertionError("unified review should run first")

    class ClarifyingCritic:
        def review_generation_bundle(self, content, outline, story, shared_context=""):
            obligation_id = re.search(r"'id': '([0-9a-f]+)'", shared_context).group(1)
            return UnifiedReviewBundle(
                continuity=ContinuityAuditReport(chapter_index=outline.chapter_index, passed=True),
                quality=QualityReviewReport(
                    scores=QualityScores(
                        logic_consistency=9,
                        character_fidelity=9,
                        foreshadowing_handling=9,
                        pacing=9,
                        style_uniformity=9,
                    )
                ),
                contract_evidence=[
                    {
                        "obligation_id": obligation_id,
                        "passed": True,
                        "confidence": 0.9,
                        "evidence": "The guard orders a reveal but no reveal occurs.",
                        "paragraph_range": "paragraph 1",
                    }
                ],
            )

    evaluator = CandidateEvaluator(
        contracts=FastContracts(),
        continuity=Continuity(),
        critic=ClarifyingCritic(),
        policy=GenerationPolicy(min_quality_score=7.5),
    )
    contract = ChapterContract(chapter_index=1, must_not_happen=["do not reveal the secret"])
    candidate = Chapter(
        index=1,
        title="Order",
        content="The guard orders a reveal but no reveal occurs.",
        beats=[
            Beat(
                scene_index=1,
                purpose="resist order",
                goal="resist order",
                outcome="no reveal",
                character_goals={"hero": "resist"},
                content="The guard orders a reveal but no reveal occurs.",
            )
        ],
    )

    result = evaluator.evaluate(
        planned_story,
        planned_story.get_outline(1),
        contract,
        candidate,
        "shared",
        1,
    )

    # Rule evidence remains authoritative: a reported real violation must be
    # repaired rather than overwritten by a reviewer pass.
    assert result.decision is GenerationDecision.REPAIR
    assert result.review_mode == "unified"


def test_advisory_review_does_not_rewrite_a_contract_compliant_candidate(planned_story) -> None:
    class AdvisoryCritic(Critic):
        def review_quality_scorecard(self, content, outline, story, extra_context=""):
            return QualityReviewReport(
                scores=QualityScores(
                    logic_consistency=8,
                    character_fidelity=8,
                    foreshadowing_handling=8,
                    pacing=8,
                    style_uniformity=8,
                ),
                issues=[
                    RevisionIssue(
                        dimension="advisory continuity risk",
                        severity="high",
                        description="Needs a human review but no automatic rewrite.",
                    )
                ],
            )

    evaluator = CandidateEvaluator(
        contracts=Contracts(),
        continuity=Continuity(),
        critic=AdvisoryCritic(),
        policy=GenerationPolicy(min_quality_score=7.5, auto_repair_review_issues=False),
    )
    candidate = Chapter(index=1, title="Stable", content="contract-safe draft")

    result = evaluator.evaluate(
        planned_story,
        planned_story.get_outline(1),
        ChapterContract(chapter_index=1),
        candidate,
        "shared",
        1,
    )

    assert result.decision is GenerationDecision.ACCEPT
    assert "quality_issue:" in result.reasons[0]
