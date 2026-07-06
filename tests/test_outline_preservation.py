from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.models import ChapterOutline
from novelforge.orchestrator.engine import NovelForgeEngine


def test_generate_beats_does_not_change_existing_outlines(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns to read the game.", title="Beats")
    engine.generate_outline(3)
    before = [outline.model_dump() for outline in story.outlines]

    engine.generate_beats(2)

    assert [outline.model_dump() for outline in story.outlines] == before


def test_ensure_outlines_appends_missing_without_rewriting_existing(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns to read the game.", title="Ensure")
    engine.generate_outline(3)
    before = [outline.model_dump() for outline in story.outlines]

    engine._ensure_outlines(5)

    assert [outline.model_dump() for outline in story.outlines[:3]] == before
    assert len(story.outlines) == 5
    assert [outline.chapter_index for outline in story.outlines] == [1, 2, 3, 4, 5]


def test_generate_outline_only_rebuilds_when_force_is_true(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns to read the game.", title="Force")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="Original One", summary="Keep me", conflict="Old"),
        ChapterOutline(chapter_index=2, title="Original Two", summary="Keep me too", conflict="Old"),
        ChapterOutline(chapter_index=3, title="Original Three", summary="Still here", conflict="Old"),
    ]
    before = [outline.model_dump() for outline in story.outlines]

    engine.generate_outline(3)

    assert [outline.model_dump() for outline in story.outlines] == before

    engine.generate_outline(3, force=True)

    assert len(story.outlines) == 3
    assert [outline.model_dump() for outline in story.outlines] != before


def test_outline_api_force_defaults_to_false() -> None:
    ENGINES.clear()
    client = TestClient(app)
    created = client.post(
        "/stories/",
        json={"premise": "A goalkeeper learns to read the game.", "title": "Outline API"},
    )
    story_id = created.json()["story"]["id"]

    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 3})
    story = client.get(f"/stories/{story_id}/").json()["story"]
    first_title = story["outlines"][0]["title"]

    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 5})
    supplemented = client.get(f"/stories/{story_id}/").json()["story"]

    assert supplemented["outlines"][0]["title"] == first_title
    assert [outline["chapter_index"] for outline in supplemented["outlines"]] == [1, 2, 3, 4, 5]

    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 2, "force": True})
    rebuilt = client.get(f"/stories/{story_id}/").json()["story"]

    assert len(rebuilt["outlines"]) == 2
