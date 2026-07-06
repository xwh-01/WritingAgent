from __future__ import annotations

import os

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.config import AppConfig, AutoRevisorConfig
from novelforge.orchestrator.engine import NovelForgeEngine


def test_director_agent_runs_dynamic_tool_steps(test_config: AppConfig) -> None:
    test_config.auto_revisor = AutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A young goalkeeper learns anticipation.", title="Director")

    run = engine.run_director_agent("继续写下一章", max_steps=3)

    assert run.status == "completed"
    assert len(run.steps) == 2
    assert [step.selected_tool for step in run.steps] == ["create_outline", "auto_write_chapter"]
    assert run.steps[-1].success
    assert story.agent_trace_runs[-1].id == run.id
    assert story.chapters


def test_director_agent_can_list_foreshadowings(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A mystery with several unresolved clues.", title="Foreshadow")
    engine.longform_manager.add_foreshadowing(story, "A locked room key is missing.", 1, 5)

    run = engine.run_director_agent("看看还有哪些伏笔没回收", max_steps=2)

    assert run.status == "completed"
    assert run.steps[0].selected_tool == "list_foreshadowings"
    assert "Found 1 foreshadowings" in run.steps[0].observation


def test_director_agent_api_and_trace_page() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post(
        "/stories/",
        json={"premise": "A young goalkeeper learns anticipation.", "title": "Director API"},
    )
    story_id = created.json()["story"]["id"]

    started = client.post(
        f"/stories/{story_id}/agent/run",
        json={"user_message": "继续写下一章", "max_steps": 3},
    )
    payload = started.json()

    assert started.status_code == 200
    assert payload["status"] == "completed"
    assert payload["steps"][0]["selected_tool"] == "create_outline"

    runs = client.get(f"/stories/{story_id}/agent/runs").json()
    assert runs["runs"][0]["id"] == payload["id"]

    detail = client.get(f"/stories/{story_id}/agent/runs/{payload['id']}").json()
    assert detail["id"] == payload["id"]

    page = client.get("/agent-trace/", params={"story_id": story_id})
    assert page.status_code == 200
    assert "Agent Trace" in page.text


def test_agents_endpoint_lists_new_agents() -> None:
    client = TestClient(app)
    agents = client.get("/agents/").json()["agents"]
    assert "supervisor" in agents
    assert "director" in agents
    assert "continuity_auditor" in agents
    assert "memory_extractor" in agents
