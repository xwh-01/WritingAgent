from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app


def test_workspace_page_and_static_assets_render() -> None:
    client = TestClient(app)

    page = client.get("/workspace/")
    trace = client.get("/agent-trace/")
    script = client.get("/workspace-static/workspace.js")
    style = client.get("/workspace-static/workspace.css")

    assert page.status_code == 200
    assert "NovelForge 工作台" in page.text
    assert "批量" in page.text
    assert "告诉 Agent 你想做什么" in page.text
    assert "运行 Agent" in page.text
    assert "演示流程" in page.text
    assert "下一步" in page.text
    assert "前置条件" in page.text
    assert "继续写下一章" in page.text
    assert "检查第5章人设" in page.text
    assert "Novel Agent Studio" in page.text
    assert "Director Agent" in page.text
    assert "上下文预览" in page.text
    assert "章节合同" in page.text
    assert 'id="contractMust"' in page.text
    assert 'id="contractMustNot"' in page.text
    assert "人物事实账本" in page.text
    assert 'id="factCharacter"' in page.text
    assert 'class="fact-table"' in page.text
    assert "辅助工具" in page.text
    assert "批量编排" in page.text
    assert trace.status_code == 200
    assert "Agent Trace" in trace.text
    assert script.status_code == 200
    assert style.status_code == 200
    assert "saveCharacterFact" in script.text
    assert ".structured-form" in style.text
    assert ".fact-table" in style.text


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
    validation = client.post(
        "/chapters/1/validate-contract",
        params={"story_id": story_id},
    )

    assert updated.status_code == 200
    assert updated.json()["chapter"]["content"] == "王绍康站在球门前。"
    assert story["content"]["chapters"]["1"]["title"] == "第一章"
    assert validation.status_code == 200
    assert "checks" in validation.json()
    assert "review_required" in validation.json()


def test_storage_status_endpoint_exposes_canonical_and_derived_boundaries() -> None:
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "一个存储边界测试", "title": "存储状态"})
    story_id = created.json()["story"]["id"]

    response = client.get(f"/stories/{story_id}/storage")
    payload = response.json()

    assert response.status_code == 200
    assert payload["canonical_store"].endswith("novelforge.db")
    assert "derived_indexes" in payload
    assert "pending_index_events" in payload
