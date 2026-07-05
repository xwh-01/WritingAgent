from __future__ import annotations

import os

from fastapi.testclient import TestClient

from novelforge.api.state import ENGINES
from novelforge.api.main import app


def test_auto_revision_background_api_and_report_markdown() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "一个少年在球场获得预判能力", "title": "后台任务API测试"})
    story_id = created.json()["story"]["id"]
    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 1})

    started = client.post(f"/chapters/1/auto-write", params={"story_id": story_id, "background": True})
    payload = started.json()
    job_id = payload["id"]

    status = client.get("/chapters/auto/status", params={"story_id": story_id, "job_id": job_id}).json()
    assert status["id"] == job_id
    assert status["status"] in {"queued", "running", "passed", "finished_with_residual_issues"}

    # Run a synchronous pass too so report existence is deterministic for this request/response test.
    client.post(f"/chapters/1/auto-write", params={"story_id": story_id})
    markdown = client.get(f"/chapters/1/report.md", params={"story_id": story_id})

    assert markdown.status_code == 200
    assert "Auto-Revision Report" in markdown.text
