from __future__ import annotations

from novelforge.orchestrator.engine import NovelForgeEngine


def test_write_chapter_auto_polishes_draft(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns anticipation.", title="Polish")
    engine.generate_outline(1)

    chapter = engine.write_chapter(1)

    assert "【润色稿】" in chapter.content


def test_write_chapter_can_disable_auto_polish(test_config) -> None:
    test_config.story.auto_polish_drafts = False
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns anticipation.", title="No Polish")
    engine.generate_outline(1)

    chapter = engine.write_chapter(1)

    assert "【润色稿】" not in chapter.content
