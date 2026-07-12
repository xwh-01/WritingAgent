from __future__ import annotations

import os

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.config import AppConfig, AutoRevisorConfig
from novelforge.core.models import Character, CharacterState, Chapter, ChapterOutline, TaskEvaluation
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


def test_director_revision_preserves_user_instruction(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一座海港城正在失去记忆。", title="定向修改")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="潮声", summary="主角抵达港口。", conflict="记忆开始消退。")
    ]
    story.chapters[1] = Chapter(index=1, title="潮声", content="原有正文", status="draft")
    story.current_chapter = 1
    captured = {}

    def fake_revise(content, report, style_guide="", revision_instruction=""):
        captured["instruction"] = revision_instruction
        return "按要求修改后的正文"

    monkeypatch.setattr(engine.editor, "revise_chapter", fake_revise)
    run = engine.run_director_agent("把第1章改得更阴冷克制，保留结尾", max_steps=3)

    assert run.status == "awaiting_approval"
    assert run.plan is not None
    assert run.plan.status == "awaiting_approval"
    assert [step.selected_tool for step in run.steps] == ["inspect_chapter", "revise_chapter"]
    assert run.steps[1].tool_args["revision_instruction"] == "把第1章改得更阴冷克制，保留结尾"
    assert captured["instruction"] == "把第1章改得更阴冷克制，保留结尾"
    assert story.chapters[1].content == "原有正文"
    proposal = story.revision_proposals[-1]
    assert proposal.id == run.proposal_ids[-1]
    assert proposal.proposed_content == "按要求修改后的正文"
    assert proposal.status == "awaiting_approval"

    chapter = engine.accept_revision_proposal(proposal.id)
    assert chapter.content == "按要求修改后的正文"
    assert proposal.status == "accepted"


def test_director_question_can_resume_same_run(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("一座海港城正在失去记忆。", title="追问恢复")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="潮声", summary="主角抵达港口。", conflict="记忆开始消退。")
    ]
    story.chapters[1] = Chapter(index=1, title="潮声", content="原有正文", status="draft")

    run = engine.run_director_agent("帮我修改一下", max_steps=1)
    assert run.status == "needs_user_input"
    assert run.pending_question == "你想修改第几章？"

    resumed = engine.resume_director_agent(run.id, "第1章", max_steps=3)
    assert resumed is run
    assert resumed.status == "awaiting_approval"
    assert resumed.pending_question == ""
    assert resumed.user_responses == ["第1章"]
    assert resumed.steps[0].step == 1
    assert len(story.agent_trace_runs) == 1


def test_revision_proposal_can_be_rejected_without_overwriting(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("旧塔每晚都会改变位置。", title="拒绝候选")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="旧塔", summary="主角发现旧塔。", conflict="地图与现实冲突。")
    ]
    story.chapters[1] = Chapter(index=1, title="旧塔", content="不可覆盖的原文", status="draft")
    monkeypatch.setattr(
        engine.editor,
        "revise_chapter",
        lambda *args, **kwargs: "未获批准的候选稿",
    )

    proposal = engine.create_revision_proposal(1, "加强悬疑感")
    rejected = engine.reject_revision_proposal(proposal.id)

    assert rejected.status == "rejected"
    assert story.chapters[1].content == "不可覆盖的原文"


def test_director_saves_checkpoint_and_continues_plan(test_config: AppConfig) -> None:
    engine = NovelForgeEngine(config=test_config)
    engine.start_new_story("A goalkeeper prepares for a decisive match.", title="Checkpoint")

    paused = engine.run_director_agent("write the next chapter", max_steps=1)
    assert paused.status == "paused"
    assert paused.plan.tasks[0].status == "completed"
    assert paused.plan.tasks[1].status == "pending"

    completed = engine.continue_director_agent(paused.id, max_steps=2)
    assert completed.status == "completed"
    assert all(task.status == "completed" for task in completed.plan.tasks)


def test_director_retries_when_evaluator_rejects_result(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    engine.start_new_story("A project status task.", title="Evaluator Retry")
    evaluations = iter([
        TaskEvaluation(
            passed=False,
            recoverable=True,
            recommended_action="retry",
            feedback="The first result lacked sufficient evidence.",
        ),
        TaskEvaluation(passed=True, recommended_action="complete"),
    ])
    monkeypatch.setattr(engine.task_evaluator, "evaluate", lambda *args, **kwargs: next(evaluations))

    run = engine.run_director_agent("show project status", max_steps=3)

    assert run.status == "completed"
    assert len(run.steps) == 2
    assert run.plan.tasks[0].attempts == 2
    assert run.plan.replan_count == 1


def test_proposal_feedback_stays_linked_to_director_run(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("雾中的旧城隐藏着一扇门。", title="候选反馈")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="门", summary="主角找到门。", conflict="门后传来熟悉声音。")
    ]
    story.chapters[1] = Chapter(index=1, title="门", content="原文", status="draft")
    monkeypatch.setattr(engine.editor, "revise_chapter", lambda *args, **kwargs: "候选正文")

    run = engine.run_director_agent("修改第1章，增强悬疑感", max_steps=3)
    first_id = run.proposal_ids[-1]
    second = engine.revise_revision_proposal(first_id, "减少解释，保留最后一句")

    assert engine.get_revision_proposal(first_id).status == "rejected"
    assert run.status == "awaiting_approval"
    assert run.plan.status == "awaiting_approval"
    assert run.proposal_ids[-1] == second.id
    assert story.chapters[1].content == "原文"


def test_rejecting_proposal_closes_waiting_run(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("雪原上只剩一串脚印。", title="拒绝运行")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="脚印", summary="主角追踪脚印。", conflict="脚印突然消失。")
    ]
    story.chapters[1] = Chapter(index=1, title="脚印", content="原文", status="draft")
    monkeypatch.setattr(engine.editor, "revise_chapter", lambda *args, **kwargs: "候选正文")

    run = engine.run_director_agent("修改第1章", max_steps=3)
    engine.reject_revision_proposal(run.proposal_ids[-1])

    assert run.status == "rejected"
    assert run.plan.status == "rejected"
    assert story.chapters[1].content == "原文"


def test_director_repairs_only_character_arc_drift_targets(test_config: AppConfig, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("苏黎在旧城追查失踪案。", title="角色弧线")
    story.characters["suli"] = Character(id="suli", name="苏黎")
    story.outlines = [
        ChapterOutline(chapter_index=1, title="旧城", summary="苏黎开始调查。", conflict="她发现危险线索。"),
        ChapterOutline(chapter_index=2, title="城堡", summary="苏黎进入城堡。", conflict="她突然改变决定。"),
    ]
    story.chapters[1] = Chapter(index=1, title="旧城", content="苏黎害怕地留在旧城调查。", status="draft")
    story.chapters[2] = Chapter(index=2, title="城堡", content="苏黎兴奋地出现在城堡。", status="draft")
    story.character_states["suli"] = [
        CharacterState(character_id="suli", chapter=1, emotional_state="恐惧", location="旧城"),
        CharacterState(character_id="suli", chapter=2, emotional_state="兴奋", location="城堡"),
    ]
    captured = {}

    def fake_revise(content, report, style_guide="", revision_instruction=""):
        captured["instruction"] = revision_instruction
        return "修复过渡后的候选正文"

    monkeypatch.setattr(engine.editor, "revise_chapter", fake_revise)
    run = engine.run_director_agent(
        "检查第1到第2章苏黎的人设是否一致；发现问题后生成修订候选稿",
        max_steps=3,
    )

    assert run.status == "awaiting_approval"
    assert [task.selected_tool for task in run.plan.tasks] == [
        "analyze_character_continuity", "revise_chapter"
    ]
    report = story.character_continuity_reports[-1]
    assert report.character_id == "suli"
    assert report.affected_chapters == [2]
    proposal = story.revision_proposals[-1]
    assert proposal.chapter_index == 2
    assert "第2章" in captured["instruction"]
    assert story.chapters[1].content == "苏黎害怕地留在旧城调查。"
    assert story.chapters[2].content == "苏黎兴奋地出现在城堡。"


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
    missing = client.get(f"/stories/{story_id}/agent/runs/missing-trace")
    assert missing.status_code == 404

    page = client.get("/agent-trace/", params={"story_id": story_id})
    assert page.status_code == 200
    assert "Agent Trace" in page.text

    proposed = client.post(
        f"/stories/{story_id}/agent/run",
        json={"user_message": "revise chapter 1 with more tension while preserving the ending", "max_steps": 3},
    )
    assert proposed.status_code == 200
    proposal_run = proposed.json()
    assert proposal_run["status"] == "awaiting_approval"
    proposal_id = proposal_run["proposal_ids"][0]
    proposal = client.get(
        f"/stories/{story_id}/revision-proposals/{proposal_id}"
    ).json()
    assert proposal["status"] == "awaiting_approval"
    accepted = client.post(
        f"/stories/{story_id}/revision-proposals/{proposal_id}/accept",
        json={},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True


def test_agents_endpoint_lists_new_agents() -> None:
    client = TestClient(app)
    agents = client.get("/agents/").json()["agents"]
    assert agents == [
        "planner",
        "writer",
        "critic",
        "editor",
        "supervisor",
        "director",
        "task_evaluator",
        "continuity_auditor",
        "memory_extractor",
        "context",
        "memory",
    ]
