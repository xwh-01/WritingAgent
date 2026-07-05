from __future__ import annotations

import os

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.config import AppConfig, AutoRevisorConfig
from novelforge.orchestrator.engine import NovelForgeEngine


def test_engine_batch_write_generates_multiple_chapters(test_config: AppConfig) -> None:
    test_config.auto_revisor = AutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一个少年成为天才门将", title="批量测试")
    engine.generate_outline(3)

    events: list[dict[str, object]] = []

    report = engine.batch_write_chapters(1, 3, use_auto_revision=True, progress_callback=events.append)

    assert report.completed == 3
    assert report.failed == 0
    assert len(story.chapters) == 3
    assert story.batch_reports
    assert all(item.word_count > 0 for item in report.results)
    assert any(event["stage"] == "beats" for event in events)
    assert any(event["stage"] == "auto_revision" for event in events)
    assert events[-1]["progress_current"] == 3


def test_batch_write_api_background_job() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "一个少年成为天才门将", "title": "批量API测试"})
    story_id = created.json()["story"]["id"]
    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 2})

    started = client.post(
        f"/stories/{story_id}/batch-write",
        json={"start_chapter": 1, "end_chapter": 2, "use_auto_revision": False, "background": True},
    )

    assert started.status_code == 200
    payload = started.json()
    assert payload["status"] in {"queued", "running_batch", "batch_finished"}
    assert payload["progress_total"] == 2
    assert "message" in payload
    assert "events" in payload
