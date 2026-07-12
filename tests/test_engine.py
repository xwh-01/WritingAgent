from __future__ import annotations

from novelforge.orchestrator.engine import NovelForgeEngine


def test_engine_core_workflow(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个机械师在废土里修复会做梦的城市", title="梦城")
    assert story.status == "planning"

    outlines = engine.generate_outline(2)
    assert len(outlines) == 2

    chapter = engine.generate_beats(1)
    assert chapter.beats

    draft = engine.write_chapter(1)
    assert draft.content
    assert draft.version == 2

    report = engine.request_review(1)
    assert report.verdict

    revised = engine.apply_revision(1)
    assert revised.version == 3
    assert revised.history
    assert engine.story.memory.chapter_summaries[1]
    assert engine.story.memory.causal_events


def test_engine_save_and_load(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个图书管理员听见书页中的未来", title="纸页未来")
    engine.generate_outline(1)
    path = engine.save_state()
    assert path.exists()

    other = NovelForgeEngine(config=test_config)
    loaded = other.load_state(story.id)
    assert loaded.title == "纸页未来"
