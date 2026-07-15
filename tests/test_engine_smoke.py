from __future__ import annotations

from novelforge.core.config import AppConfig
from novelforge.orchestrator.engine import NovelForgeEngine


def test_engine_runs_complete_reliable_chapter_flow(tmp_path) -> None:
    config = AppConfig.model_validate(
        {
            "llm": {"provider": "mock"},
            "indexes": {"vector_store": "in_memory"},
            "storage": {
                "database_path": str(tmp_path / "novelforge.db"),
                "artifact_directory": str(tmp_path / "artifacts"),
                "vector_index_directory": str(tmp_path / "vector"),
                "graph_index_directory": str(tmp_path / "graph"),
                "full_text_index_path": str(tmp_path / "fts.sqlite3"),
            },
            "story": {
                "default_chapters": 2,
                "auto_polish_drafts": False,
                "prose_target_words": 600,
            },
            "generation": {"min_quality_score": 6.0, "max_repairs": 1},
        }
    )
    engine = NovelForgeEngine(config)
    reloaded_engine = None
    try:
        story = engine.start_new_story(
            "A courier must choose truth over family loyalty.",
            "Courier",
        )
        engine.generate_outline(2)
        planned = engine.generate_beats(1)
        assert sum(beat.target_length for beat in planned.beats) == 600

        chapter = engine.write_chapter(1)
        assert chapter.content
        assert engine.current_story.knowledge.sources[1].manuscript_version == chapter.version
        assert engine.current_story.quality.generation_reports[1].accepted is True

        reloaded_engine = NovelForgeEngine(config)
        reloaded = reloaded_engine.load_state(story.id)
        reloaded.assert_consistent()
        assert reloaded.manuscript.chapters[1].content == chapter.content
        assert engine.repository.pending_index_event_count(story.id) == 0
    finally:
        if reloaded_engine is not None:
            reloaded_engine.close()
        engine.close()
