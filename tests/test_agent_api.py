from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app


def test_agent_goal_is_available_through_http(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NOVELFORGE_LLM_PROVIDER", "mock")
    monkeypatch.setenv("NOVELFORGE_VECTOR_BACKEND", "in_memory")
    monkeypatch.setenv("NOVELFORGE_DATABASE_PATH", str(tmp_path / "novelforge.db"))
    monkeypatch.setenv("NOVELFORGE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NOVELFORGE_CHROMA_DIR", str(tmp_path / "vector"))
    monkeypatch.setenv("NOVELFORGE_GRAPH_DIR", str(tmp_path / "graph"))
    monkeypatch.setenv("NOVELFORGE_FTS_PATH", str(tmp_path / "fts.sqlite3"))

    with TestClient(app) as client:
        created = client.post(
            "/stories/",
            json={"title": "Courier", "premise": "A courier chooses truth."},
        )
        assert created.status_code == 200
        story_id = created.json()["story"]["id"]

        started = client.post(
            f"/stories/{story_id}/agent-runs",
            json={"goal": "继续写第 1 章", "max_steps": 8},
        )
        assert started.status_code == 200
        run = started.json()
        assert run["status"] == "completed"

        details = client.get(f"/stories/{story_id}/agent-runs/{run['id']}")
        assert details.status_code == 200
        assert details.json()["candidates"][0]["status"] == "committed"
