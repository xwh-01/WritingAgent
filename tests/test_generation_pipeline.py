from __future__ import annotations

from novelforge.application.generation import (
    CandidateEvaluator,
    ChapterGenerationPipeline,
    GenerationPolicy,
)
from novelforge.domain import (
    Chapter,
    ContinuityAuditReport,
    GenerationDecision,
    QualityReviewReport,
    QualityScores,
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
