from __future__ import annotations

from novelforge.core.config import AppConfig, AutoRevisorConfig as AppAutoRevisorConfig
from novelforge.core.models import ChapterOutline
from novelforge.core.models import Story
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.orchestrator.job_registry import AutoRevisionJobRegistry
from novelforge.storage.repository import StoryRepository


def test_story_repository_lists_and_exports_report(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="仓库测试")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="第一扑", summary="他第一次扑救。", conflict="他必须证明自己。")
    ]
    result = engine.auto_write_chapter(1)

    repository = engine.repository
    records = repository.list_records()
    output = repository.export_auto_revision_report(story, result)

    assert any(record.id == str(story.id) for record in records)
    assert output.exists()
    assert "Auto-Revision Report" in output.read_text(encoding="utf-8")


def test_repository_imports_legacy_json_once_and_records_index_event(tmp_path) -> None:
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    story = Story(title="Legacy", premise="A migration test")
    (legacy_dir / f"{story.id}.json").write_text(story.model_dump_json(), encoding="utf-8")
    repository = StoryRepository(
        database_path=tmp_path / "novelforge.db",
        artifact_directory=tmp_path / "artifacts",
        legacy_state_directory=legacy_dir,
    )

    loaded = repository.load(story.id)
    events = repository.pending_index_events()

    assert loaded.id == story.id
    assert repository.exists(story.id)
    assert any(event["event_type"] == "legacy_json_imported" for event in events)
    assert repository.database_path.exists()


def test_story_aggregate_migrates_flat_state_to_domain_boundaries() -> None:
    legacy = {
        "title": "Nested Story",
        "premise": "A domain boundary migration test",
        "outlines": [],
        "chapters": {},
        "characters": {},
        "character_facts": [],
        "memory_cards": [],
        "auto_revision_reports": {},
        "revision_proposals": [],
        "agent_runs": [],
        "agent_trace_runs": [],
    }

    story = Story.model_validate(legacy)
    serialized = story.model_dump()

    assert story.content.chapters == {}
    assert story.memory.facts == []
    assert story.quality.revision_proposals == []
    assert story.agent_runs.director == []
    assert set(("content", "memory", "quality", "agent_runs")).issubset(serialized)
    assert "chapters" not in serialized
    assert "character_facts" not in serialized


def test_rebuild_indexes_uses_canonical_story_state(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A keeper protects a secret city.", title="Index Rebuild")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="First Save", summary="The keeper finds a secret.", conflict="Danger arrives.")
    ]
    engine.update_chapter_content(1, "alpha index rebuild evidence")
    engine.vector_store.delete_story(str(story.id))
    engine.text_store.delete_story(str(story.id))
    engine.graph_store.delete_story(str(story.id))

    result = engine.rebuild_derived_indexes()

    assert result["chapters"] == 1
    assert result["events_processed"] >= 1
    assert engine.text_store.search("alpha", story_id=str(story.id))
    assert engine.vector_store.query("plot_summaries", "secret", story_id=str(story.id))


def test_auto_revision_job_registry_runs_background_job(test_config: AppConfig) -> None:
    test_config.auto_revisor = AppAutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年在球场获得预判能力", title="任务测试")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="第一扑", summary="他第一次扑救。", conflict="他必须证明自己。")
    ]
    registry = AutoRevisionJobRegistry()

    job = registry.start(engine, str(story.id), 1)
    registry._threads[job.id].join(timeout=10)
    finished = registry.get(job.id)

    assert finished is not None
    assert finished.status == "passed"
    assert finished.result is not None
