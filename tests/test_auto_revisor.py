from __future__ import annotations

from novelforge.core.config import AppConfig, AutoRevisorConfig as AppAutoRevisorConfig
from novelforge.core.models import ChapterOutline
from novelforge.orchestrator.engine import NovelForgeEngine


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
