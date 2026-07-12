from __future__ import annotations

from pathlib import Path
from typing import Any

from evals.run_eval import CASES_DIR, run_all
from novelforge.core.config import AppConfig, AutoRevisorConfig
from novelforge.core.models import AgentTraceRun, ChapterOutline, DirectorPlan, DirectorTask
from novelforge.llm.base import LLMClient
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.orchestrator.tool_registry import ToolRegistry
from novelforge.orchestrator.trace_exporter import render_debug_report, trace_to_json


class SequencedDirectorLLM(LLMClient):
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls = 0

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        import json

        index = min(self.calls, len(self.decisions) - 1)
        self.calls += 1
        return json.dumps(self.decisions[index])


def test_trace_schema_and_debug_export(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    engine.start_new_story("A concise trace demo.", title="Trace")

    run = engine.run_director_agent("show status", max_steps=1)
    payload = trace_to_json(run)
    markdown = render_debug_report(run)

    assert payload["id"] == run.id
    assert payload["trace_events"]
    assert "Agent Debug Report" in markdown
    assert "Memory Hits" in markdown


def test_tool_registry_returns_structured_arg_validation_error(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    engine.start_new_story("Tool validation demo.", title="Tools")
    result = ToolRegistry(engine).execute("create_beats", {"chapter_index": "bad"}, run_id="run-test")

    assert result["success"] is False
    assert result["error_type"] == "tool_arg_invalid"
    assert result["trace_event"]["selected_tool"] == "create_beats"


def test_tool_registry_error_trace_does_not_require_active_story(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    result = ToolRegistry(engine).execute("unknown_tool", {}, run_id="run-no-story")

    assert result["success"] is False
    assert result["trace_event"]["story_id"] == ""
    assert result["error_type"] == "tool_arg_invalid"


def test_export_filename_sanitizes_title(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    engine.start_new_story("Unsafe title export.", title='Bad:/\\*?"<>|Title')

    filename = engine._safe_export_filename(engine.story.title)

    assert filename == "Bad_Title"
    assert all(char not in filename for char in '<>:"/\\|?*')


def test_director_repairs_missing_precondition_with_outline(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper needs a first chapter.", title="Recover Outline")
    run = engine.run_director_agent("write chapter one", max_steps=3)

    assert run.status == "completed"
    assert any(event["selected_tool"] == "create_outline" for event in run.trace_events)
    assert [task.selected_tool for task in run.plan.tasks] == ["create_outline", "auto_write_chapter"]
    assert story.outlines


def test_director_handles_tool_arg_invalid_without_crashing(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A validation recovery story.", title="Arg Recovery")
    run = AgentTraceRun(
        id="invalid-plan-run",
        story_id=str(story.id),
        user_message="make beats",
        status="paused",
        plan=DirectorPlan(
            objective="make beats",
            tasks=[DirectorTask(
                description="invalid model arguments",
                selected_tool="create_beats",
                tool_args={"chapter_index": "bad"},
                max_attempts=2,
            )],
        ),
    )
    story.agent_trace_runs.append(run)

    run = engine.continue_director_agent(run.id, max_steps=4)

    assert run.status == "failed"
    assert any(step.error_type == "tool_arg_invalid" for step in run.steps)
    assert run.plan.tasks[0].attempts == 2


def test_auto_revisor_writes_round_trace(test_config: AppConfig) -> None:
    test_config.auto_revisor = AutoRevisorConfig(max_rounds=2, pass_threshold=8.5)
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns anticipation.", title="Auto Trace")
    story.outlines = [
        ChapterOutline(
            chapter_index=1,
            title="First Save",
            summary="The hero discovers anticipation.",
            conflict="He must prove it under pressure.",
            pov_character="hero",
        )
    ]

    result = engine.auto_write_chapter(1)

    assert result.trace_events
    assert any(event["action"].startswith("review_round_") for event in result.trace_events)


def test_eval_runner_writes_markdown_and_json(tmp_path: Path) -> None:
    report_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    results = run_all(CASES_DIR, report_path, json_path)

    assert results
    assert report_path.exists()
    assert json_path.exists()
    assert '"case_id"' in json_path.read_text(encoding="utf-8")
