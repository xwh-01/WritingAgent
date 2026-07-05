from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app


def test_workspace_page_and_static_assets_render() -> None:
    client = TestClient(app)

    page = client.get("/workspace/")
    script = client.get("/workspace-static/workspace.js")
    style = client.get("/workspace-static/workspace.css")

    assert page.status_code == 200
    assert "NovelForge 工作台" in page.text
    assert script.status_code == 200
    assert style.status_code == 200


def test_update_chapter_content_endpoint() -> None:
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "一个门将成长故事", "title": "工作台测试"})
    story_id = created.json()["story"]["id"]
    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 1})

    updated = client.put(
        "/chapters/1/content",
        params={"story_id": story_id},
        json={"title": "第一章", "content": "王绍康站在球门前。", "status": "draft"},
    )
    story = client.get(f"/stories/{story_id}/").json()["story"]

    assert updated.status_code == 200
    assert updated.json()["chapter"]["content"] == "王绍康站在球门前。"
    assert story["chapters"]["1"]["title"] == "第一章"
