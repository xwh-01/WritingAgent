from __future__ import annotations

from novelforge.core.config import AppConfig, AutoRevisorConfig as AppAutoRevisorConfig
from novelforge.core.models import ChapterOutline
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.orchestrator.job_registry import AutoRevisionJobRegistry
from novelforge.storage.repository import StoryRepository


def test_story_repository_lists_and_exports_report(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="仓库测试")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="第一扑", summary="他第一次扑救。", conflict="他必须证明自己。")
    ]
    result = engine.auto_write_chapter(1)

    repository = engine.repository
    records = repository.list_records()
    output = repository.export_auto_revision_report(story, result)

    assert any(record.id == str(story.id) for record in records)
    assert output.exists()
    assert "Auto-Revision Report" in output.read_text(encoding="utf-8")


def test_auto_revision_job_registry_runs_background_job(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="任务测试")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="第一扑", summary="他第一次扑救。", conflict="他必须证明自己。")
    ]
    registry = AutoRevisionJobRegistry()

    job = registry.start(engine, str(story.id), 1)
    registry._threads[job.id].join(timeout=10)
    finished = registry.get(job.id)

    assert finished is not None
    assert finished.status == "passed"
    assert finished.result is not None
