from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.core.models import (
    CausalEvent,
    Character,
    CharacterState,
    Chapter,
    ChapterOutline,
    ChapterSummary,
    Foreshadowing,
    Story,
)
from novelforge.dashboard.data_provider import DashboardDataProvider


def make_dashboard_story() -> Story:
    story = Story(title="门将之路", premise="少年从游戏中学会预判。", genre="sports")
    story.current_chapter = 4
    story.content.outlines.append(
        ChapterOutline(chapter_index=1, title="初见后羿", summary="主角发现预判能力。", conflict="秘密带来危机")
    )
    story.content.chapters[1] = Chapter(index=1, title="初见后羿", content="王绍康在球场发现秘密。他扑救成功。", status="revised")
    story.memory.foreshadowings.append(
        Foreshadowing(
            id="fs-1",
            description="后羿预判感会在决赛回收",
            created_chapter=1,
            target_chapter=3,
        )
    )
    story.content.characters["hero"] = Character(id="hero", name="王绍康")
    story.memory.states["hero"] = [
        CharacterState(character_id="hero", chapter=1, emotional_state="兴奋", location="球场")
    ]
    story.memory.chapter_summaries[1] = ChapterSummary(
        chapter_index=1,
        scene_summaries=["王绍康第一次完成关键扑救"],
        chapter_summary="王绍康在球场发现自己的预判能力。",
        key_events=["ev-1"],
    )
    story.memory.causal_events.append(CausalEvent(id="ev-1", chapter=1, description="王绍康完成关键扑救"))
    return story


def test_dashboard_data_provider_marks_overdue() -> None:
    data = DashboardDataProvider(make_dashboard_story()).get_all_data()

    assert data.story_overview["title"] == "门将之路"
    assert data.foreshadowings[0]["status"] == "overdue"
    assert data.character_timeline["王绍康"][0]["location"] == "球场"
    assert data.pacing_heatmap[0]["conflict_intensity"] >= 1
    assert data.causality_graph["nodes"][0]["id"] == "ev-1"


def test_dashboard_page_renders() -> None:
    client = TestClient(app)
    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert "故事全景仪表盘" in response.text


def test_auto_status_endpoint_renders() -> None:
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "一个测试故事", "title": "API状态测试"})
    story_id = created.json()["story"]["id"]
    response = client.get("/chapters/auto/status", params={"story_id": story_id})

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
