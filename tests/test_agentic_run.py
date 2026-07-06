from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.config import AppConfig, AutoRevisorConfig
from novelforge.orchestrator.engine import NovelForgeEngine


def test_agentic_writing_run_executes_explainable_task_queue(test_config: AppConfig) -> None:
    test_config.auto_revisor = AutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper becomes a genius after learning anticipation.", title="Agentic")
    events: list[dict[str, object]] = []

    run = engine.agentic_writing_run(
        "Write two chapters with continuity checks and memory updates.",
        1,
        2,
        use_auto_revision=False,
        progress_callback=events.append,
    )

    assert run.status == "completed"
    assert run.failed_tasks == 0
    assert run.completed_tasks == len(run.tasks)
    assert {task.action for task in run.tasks} >= {
        "ensure_outline",
        "generate_beats",
        "write_chapter",
        "audit_chapter_continuity",
        "memory_checkpoint",
    }
    assert len(story.chapters) == 2
    assert story.agent_runs[-1].id == run.id
    assert story.memory_cards
    assert all(task.status == "completed" for task in run.tasks)
    assert any(event.get("agent") == "SupervisorAgent" for event in events)
    assert any(event.get("action") == "memory_checkpoint" for event in events)


def test_agentic_run_api_background_job() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post(
        "/stories/",
        json={"premise": "A young goalkeeper trains under pressure.", "title": "Agentic API"},
    )
    story_id = created.json()["story"]["id"]

    started = client.post(
        f"/stories/{story_id}/agentic-run",
        json={
            "objective": "Write one chapter and show the agent task trace.",
            "start_chapter": 1,
            "end_chapter": 1,
            "use_auto_revision": False,
            "background": True,
        },
    )

    assert started.status_code == 200
    job_id = started.json()["id"]
    payload = {}
    for _ in range(20):
        payload = client.get("/chapters/auto/status", params={"story_id": story_id, "job_id": job_id}).json()
        if payload["status"] in {"agentic_finished", "agentic_finished_with_failures", "failed"}:
            break
        time.sleep(0.05)

    assert payload["id"] == job_id
    assert payload["status"] == "agentic_finished"
    assert payload["autonomous_result"]["status"] == "completed"
    assert any(event.get("agent") for event in payload["events"])
