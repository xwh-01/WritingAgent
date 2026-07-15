from __future__ import annotations

import pytest

from novelforge.application.chapter_workflow import ChapterWorkflow
from novelforge.application.commits import StoryCommitCoordinator
from novelforge.application.generation import ChapterAssessment, GenerationOutcome
from novelforge.application.story_domains import ManuscriptService, QualityService
from novelforge.core.exceptions import GenerationRejected
from novelforge.domain import (
    Chapter,
    ChapterSummary,
    ContinuityAuditReport,
    GenerationDecision,
    QualityReviewReport,
    QualityScores,
    content_digest,
)
from novelforge.longform.knowledge_pipeline import ChapterKnowledgePipeline
from novelforge.storage.repository import StoryRepository


class Indexes:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def rebuild(self, story):
        if self.fail:
            raise RuntimeError("index unavailable")
        return {"chapters": len(story.manuscript.chapters)}


class KnowledgeProcessor:
    def process_new_chapter(self, story, chapter_index, content):
        story.knowledge.chapter_summaries[chapter_index] = ChapterSummary(
            chapter_index=chapter_index,
            chapter_summary=content,
        )
        return {"pacing": {}, "pacing_warning": "", "extraction": None}


class Generator:
    def __init__(self, outcome: GenerationOutcome) -> None:
        self.outcome = outcome

    def generate(self, story, outline, contract, polish):
        return self.outcome


def outcome(accepted: bool) -> GenerationOutcome:
    decision = GenerationDecision.ACCEPT if accepted else GenerationDecision.REJECT
    assessment = ChapterAssessment(
        attempt=1,
        contract_checks=(),
        continuity=ContinuityAuditReport(chapter_index=1, passed=True),
        quality=QualityReviewReport(
            scores=QualityScores(
                logic_consistency=9,
                character_fidelity=9,
                foreshadowing_handling=9,
                pacing=9,
                style_uniformity=9,
            )
        ),
        score=9,
        decision=decision,
        reasons=() if accepted else ("quality",),
    )
    return GenerationOutcome(
        candidate=Chapter(index=1, title="The Choice", content="Approved prose."),
        accepted=accepted,
        assessments=(assessment,),
    )


def workflow(tmp_path, generation_outcome, indexes=None):
    repository = StoryRepository(tmp_path / "novelforge.db")
    coordinator = StoryCommitCoordinator(repository, indexes or Indexes())
    return (
        ChapterWorkflow(
            generation=Generator(generation_outcome),
            knowledge=ChapterKnowledgePipeline(KnowledgeProcessor()),
            manuscripts=ManuscriptService(),
            quality=QualityService(),
            commits=coordinator,
        ),
        repository,
    )


def test_accepted_candidate_commits_prose_knowledge_and_report(tmp_path, planned_story) -> None:
    use_case, repository = workflow(tmp_path, outcome(True))
    result = use_case.write(
        planned_story,
        1,
        planned_story.design.chapter_contracts[1],
        lambda story, chapter, content: content,
    )

    saved = repository.load(planned_story.id)
    assert result.chapter.content == "Approved prose."
    assert saved.knowledge.sources[1].content_digest == content_digest("Approved prose.")
    assert saved.quality.generation_reports[1].accepted is True
    assert repository.pending_index_event_count(saved.id) == 0
    saved.assert_consistent()


def test_rejected_candidate_never_enters_manuscript(tmp_path, planned_story) -> None:
    use_case, repository = workflow(tmp_path, outcome(False))

    with pytest.raises(GenerationRejected) as raised:
        use_case.write(
            planned_story,
            1,
            planned_story.design.chapter_contracts[1],
            lambda story, chapter, content: content,
        )

    saved = repository.load(planned_story.id)
    assert saved.manuscript.chapters == {}
    assert saved.quality.generation_reports[1].accepted is False
    assert raised.value.story == saved


def test_index_failure_keeps_canonical_commit_and_pending_outbox(tmp_path, planned_story) -> None:
    use_case, repository = workflow(tmp_path, outcome(True), Indexes(fail=True))
    result = use_case.write(
        planned_story,
        1,
        planned_story.design.chapter_contracts[1],
        lambda story, chapter, content: content,
    )

    assert result.chapter.content == "Approved prose."
    assert repository.load(planned_story.id).manuscript.chapters[1].content
    assert repository.pending_index_event_count(planned_story.id) == 1
