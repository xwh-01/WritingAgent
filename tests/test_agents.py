from __future__ import annotations

from novelforge.agents import CriticAgent, EditorAgent, PlannerAgent, WriterAgent
from novelforge.llm.mock_client import MockLLMClient


def test_planner_generates_outline_and_beats() -> None:
    planner = PlannerAgent(MockLLMClient())
    outlines = planner.generate_outline("主角寻找失落的城市", 2)
    assert len(outlines) == 2
    beats = planner.generate_beats(outlines[0])
    assert beats


def test_writer_critic_editor_flow() -> None:
    llm = MockLLMClient()
    planner = PlannerAgent(llm)
    outline = planner.generate_outline("主角寻找失落的城市", 1)[0]
    beats = planner.generate_beats(outline)
    content = WriterAgent(llm).write_chapter(1, outline, beats, "测试上下文")
    assert content
    report = CriticAgent(llm).review_chapter(content, outline, [], [])
    assert report.suggestions
    revised = EditorAgent(llm).revise_chapter(content, report)
    assert revised
