from __future__ import annotations

from novelforge.core.config import AppConfig, AutoRevisorConfig as AppAutoRevisorConfig
import pytest

from novelforge.core.models import (
    AutoRevisionReport,
    AutoRevisionRoundReport,
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    QualityReviewReport,
    QualityScores,
    RevisionIssue,
    Story,
)
from novelforge.orchestrator.auto_revisor import AutoRevisor, AutoRevisorConfig
from novelforge.orchestrator.engine import NovelForgeEngine


class FakeAssembler:
    last_context_stats: dict = {}

    def assemble_writing_context(self, *_args) -> str:
        return "context"


class FakeCritic:
    llm = None

    def __init__(self, scores: list[float]) -> None:
        self.scores = iter(scores)

    def review_quality_scorecard(self, *_args) -> QualityReviewReport:
        score = next(self.scores)
        return QualityReviewReport(
            scores=QualityScores(
                logic_consistency=score,
                character_fidelity=score,
                foreshadowing_handling=score,
                pacing=score,
                style_uniformity=score,
            )
        )


class FakeEditor:
    def __init__(self, revised: str) -> None:
        self.revised = revised

    def revise_from_quality_report(self, *_args) -> str:
        return self.revised


def make_revisor(
    *,
    scores: list[float],
    revised: str,
    checker,
    max_rounds: int = 2,
) -> AutoRevisor:
    story = Story(title="Test", premise="Test")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="One", summary="Summary", conflict="Conflict")
    ]
    story.content.chapter_contracts[1] = ChapterContract(chapter_index=1)
    return AutoRevisor(
        story=story,
        writer=object(),
        critic=FakeCritic(scores),
        editor=FakeEditor(revised),
        assembler=FakeAssembler(),
        config=AutoRevisorConfig(max_rounds=max_rounds, pass_threshold=8.5, score_samples=1),
        continuity_checker=checker,
    )


def high_continuity_issue(description: str) -> RevisionIssue:
    return RevisionIssue(
        dimension="continuity:character_state",
        severity="high",
        description=description,
    )


def test_continuity_is_rechecked_for_each_current_revision() -> None:
    checked: list[str] = []

    def checker(_index: int, content: str) -> list[RevisionIssue]:
        checked.append(content)
        return [high_continuity_issue("old issue")] if content == "draft" else []

    result = make_revisor(scores=[9.0, 9.0], revised="fixed", checker=checker).run(
        1,
        initial_content="draft",
    )

    assert result.passed
    assert checked == ["draft", "fixed"]
    assert any(issue.description == "old issue" for issue in result.rounds[0].review_report.issues)
    assert not any(issue.description == "old issue" for issue in result.rounds[1].review_report.issues)


def test_legacy_static_continuity_issues_are_not_reused_after_first_round() -> None:
    old_issue = high_continuity_issue("legacy initial issue")
    result = make_revisor(scores=[9.0, 9.0], revised="fixed", checker=None).run(
        1,
        continuity_issues=[old_issue],
        initial_content="draft",
    )

    assert result.passed
    assert any(issue.description == "legacy initial issue" for issue in result.rounds[0].review_report.issues)
    assert not any(issue.description == "legacy initial issue" for issue in result.rounds[1].review_report.issues)


def test_new_continuity_issue_in_revision_blocks_next_round() -> None:
    def checker(_index: int, content: str) -> list[RevisionIssue]:
        return [high_continuity_issue("new issue")] if content == "broken" else []

    result = make_revisor(
        scores=[8.0, 9.0, 9.0],
        revised="broken",
        checker=checker,
    ).run(1, initial_content="draft")

    assert not result.passed
    assert any(issue.description == "new issue" for issue in result.rounds[1].review_report.issues)


def test_continuity_checker_failure_is_a_high_hard_failure() -> None:
    def checker(_index: int, _content: str) -> list[RevisionIssue]:
        raise RuntimeError("auditor unavailable")

    result = make_revisor(
        scores=[9.0, 9.0],
        revised="revision",
        checker=checker,
        max_rounds=1,
    ).run(1, initial_content="draft")

    issue = next(issue for issue in result.rounds[0].review_report.issues if issue.dimension == "continuity_audit")
    assert issue.severity == "high"
    assert "auditor unavailable" in issue.description
    assert not result.rounds[0].review_report.hard_constraints_passed
    assert not result.passed


def test_final_review_rechecks_final_content_and_records_residual_issue() -> None:
    checked: list[str] = []

    def checker(_index: int, content: str) -> list[RevisionIssue]:
        checked.append(content)
        return [high_continuity_issue("final regression")] if content == "final" else []

    result = make_revisor(
        scores=[8.0, 9.0],
        revised="final",
        checker=checker,
        max_rounds=1,
    ).run(1, initial_content="draft")

    assert checked == ["draft", "final"]
    assert any(issue.description == "final regression" for issue in result.residual_issues)
    assert not result.passed
    final_trace = next(event for event in result.trace_events if event["action"] == "final_review")
    assert "continuity_issues=1" in final_trace["output_summary"]


def test_final_review_can_pass_after_last_revision() -> None:
    result = make_revisor(
        scores=[8.0, 9.0],
        revised="final",
        checker=lambda *_args: [],
        max_rounds=1,
    ).run(1, initial_content="draft")

    assert result.passed
    assert result.final_content == "final"
    assert result.final_score == 9.0


def test_auto_write_generates_report(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=3, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="天才门将")
    story.content.outlines = [
        ChapterOutline(
            chapter_index=1,
            title="第一扑",
            summary="王绍康第一次发现自己的门将天赋。",
            conflict="他必须在质疑中完成关键扑救。",
            pov_character="主角",
        )
    ]

    result = engine.auto_write_chapter(1)

    assert result.rounds
    assert result.passed
    assert result.final_score >= 8.5
    assert 1 in engine.story.quality.auto_revision_reports
    assert engine.story.content.chapters[1].content


def test_auto_write_records_residual_issues_when_threshold_too_high(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=1, pass_threshold=9.9)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="天才门将")
    story.content.outlines = [
        ChapterOutline(
            chapter_index=1,
            title="第一扑",
            summary="王绍康第一次发现自己的门将天赋。",
            conflict="他必须在质疑中完成关键扑救。",
            pov_character="主角",
        )
    ]

    result = engine.auto_write_chapter(1)

    assert not result.passed
    assert result.final_score < 9.9
    assert result.residual_issues


def prepared_commit_engine(test_config: AppConfig, chapter: Chapter | None) -> NovelForgeEngine:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("Premise", title="Commit safety")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="One", summary="Summary", conflict="Conflict")
    ]
    story.content.chapter_contracts[1] = ChapterContract(chapter_index=1)
    if chapter is not None:
        story.content.chapters[1] = chapter
    return engine


def failed_report(content: str = "rejected candidate") -> AutoRevisionReport:
    return AutoRevisionReport(
        chapter_index=1,
        final_content=content,
        final_score=7.0,
        passed=False,
        residual_issues=[RevisionIssue(dimension="quality", severity="high", description="not ready")],
    )


def passed_report(content: str = "approved candidate") -> AutoRevisionReport:
    review = QualityReviewReport(
        scores=QualityScores(
            logic_consistency=9,
            character_fidelity=9,
            foreshadowing_handling=9,
            pacing=9,
            style_uniformity=9,
        ),
        hard_constraints_passed=True,
    )
    return AutoRevisionReport(
        chapter_index=1,
        final_content=content,
        final_score=9.0,
        passed=True,
        rounds=[
            AutoRevisionRoundReport(
                round=1,
                review_report=review,
                revised_content=content,
                total_score=9.0,
            )
        ],
    )


def test_failed_auto_revision_preserves_official_chapter_and_skips_memory(test_config, monkeypatch) -> None:
    old = Chapter(
        index=1,
        title="Old",
        content="official content",
        version=7,
        status="revised",
        beats=[Beat(scene_index=1, description="official beat", goal="goal", outcome="outcome")],
    )
    old.history.append(old.snapshot())
    engine = prepared_commit_engine(test_config, old)
    before = old.model_dump()
    memory_calls: list[int] = []
    monkeypatch.setattr(AutoRevisor, "run", lambda *_args, **_kwargs: failed_report())
    monkeypatch.setattr(engine, "_process_chapter_memory", lambda *_args: memory_calls.append(1))

    result = engine.auto_write_chapter(1)

    assert not result.passed
    assert engine.story.content.chapters[1].model_dump() == before
    assert memory_calls == []
    assert engine.story.quality.auto_revision_reports[1].final_content == "rejected candidate"


def test_failed_new_chapter_leaves_no_official_candidate(test_config, monkeypatch) -> None:
    engine = prepared_commit_engine(test_config, None)
    candidate = Chapter(index=1, title="One", content="generated candidate")
    monkeypatch.setattr(engine, "_compose_chapter_by_scenes", lambda *_args: candidate)
    monkeypatch.setattr(AutoRevisor, "run", lambda *_args, **_kwargs: failed_report("generated candidate"))

    result = engine.auto_write_chapter(1)

    assert not result.passed
    assert 1 not in engine.story.content.chapters
    assert result.final_content == "generated candidate"


def test_passed_auto_revision_commits_and_updates_memory_once(test_config, monkeypatch) -> None:
    old = Chapter(index=1, title="Old", content="official content", version=4, status="reviewed")
    engine = prepared_commit_engine(test_config, old)
    memory_calls: list[str] = []
    monkeypatch.setattr(AutoRevisor, "run", lambda *_args, **_kwargs: passed_report())
    monkeypatch.setattr(engine, "_process_chapter_memory", lambda _story, chapter: memory_calls.append(chapter.content))

    result = engine.auto_write_chapter(1)

    chapter = engine.story.content.chapters[1]
    assert result.passed
    assert chapter.content == "approved candidate"
    assert chapter.version == 5
    assert len(chapter.history) == 1
    assert memory_calls == ["approved candidate"]


def test_passed_placeholder_chapter_keeps_generated_candidate_beats(test_config, monkeypatch) -> None:
    placeholder = Chapter(index=1, title="One", content="", version=1)
    engine = prepared_commit_engine(test_config, placeholder)
    generated_beat = Beat(scene_index=1, description="generated beat", goal="goal", outcome="outcome")
    candidate = Chapter(index=1, title="One", content="draft", beats=[generated_beat])
    monkeypatch.setattr(engine, "_compose_chapter_by_scenes", lambda *_args: candidate)
    monkeypatch.setattr(AutoRevisor, "run", lambda *_args, **_kwargs: passed_report())
    monkeypatch.setattr(engine, "_process_chapter_memory", lambda *_args: None)

    engine.auto_write_chapter(1)

    chapter = engine.story.content.chapters[1]
    assert chapter.content == "approved candidate"
    assert [beat.description for beat in chapter.beats] == ["generated beat"]


def test_auto_revisor_exception_restores_official_chapter(test_config, monkeypatch) -> None:
    old = Chapter(index=1, title="Old", content="official content", version=3, status="revised")
    engine = prepared_commit_engine(test_config, old)
    before = old.model_dump()

    def explode(*_args, **_kwargs):
        raise RuntimeError("revision crashed")

    monkeypatch.setattr(AutoRevisor, "run", explode)

    with pytest.raises(RuntimeError, match="revision crashed"):
        engine.auto_write_chapter(1)

    assert engine.story.content.chapters[1].model_dump() == before
    assert engine.auto_status == "failed"
