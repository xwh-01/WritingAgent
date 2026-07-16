from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_domain_has_no_infrastructure_dependencies() -> None:
    forbidden = ("novelforge.storage", "novelforge.indexes", "novelforge.application")
    for path in (ROOT / "novelforge" / "domain").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith(forbidden) for name in imports), path


def test_removed_compatibility_architecture_does_not_return() -> None:
    removed = [
        ROOT / "novelforge" / "core" / "models.py",
        ROOT / "novelforge" / "orchestrator" / "auto_revisor.py",
        ROOT / "novelforge" / "orchestrator" / "job_registry.py",
        ROOT / "novelforge" / "agents" / "director.py",
    ]
    assert not any(path.exists() for path in removed)
    engine_lines = (
        (ROOT / "novelforge" / "orchestrator" / "engine.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(engine_lines) < 500


def test_operational_agent_state_is_not_embedded_in_story() -> None:
    story_source = (ROOT / "novelforge" / "domain" / "story.py").read_text(encoding="utf-8")
    assert "StoryRuns" not in story_source
    assert "runs:" not in story_source
    assert (ROOT / "novelforge" / "storage" / "agent_runs.py").exists()
    assert (ROOT / "novelforge" / "orchestrator" / "runtime.py").exists()
    assert (ROOT / "novelforge" / "agents" / "story_orchestrator.py").exists()
