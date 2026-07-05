from __future__ import annotations

from novelforge.core.models import CausalEvent, Character, Foreshadowing, Story
from novelforge.llm.mock_client import MockLLMClient
from novelforge.longform.causality import CausalityTracker
from novelforge.longform.character_state import CharacterStateTracker
from novelforge.longform.foreshadowing import ForeshadowingTracker
from novelforge.longform.manager import LongformManager
from novelforge.longform.pacing import PacingAnalyzer
from novelforge.longform.summaries import SummaryManager


def test_foreshadowing_tracker_registers_and_fulfills() -> None:
    story = Story(title="测试", premise="秘密钥匙")
    tracker = ForeshadowingTracker()
    item = tracker.register(
        story,
        Foreshadowing(id="fs-1", description="神秘钥匙将在后文打开密室", created_chapter=1, target_chapter=3),
    )

    assert tracker.get_pending(story) == [item]
    tracker.fulfill(story, "fs-1", 3)
    assert tracker.get_pending(story) == []


def test_causality_tracker_detects_future_cause_conflict() -> None:
    story = Story(title="测试", premise="因果测试")
    tracker = CausalityTracker()
    tracker.add_event(story, CausalEvent(id="ev-future", chapter=5, description="未来事件"))

    issues = tracker.check_conflicts(
        story,
        CausalEvent(id="ev-now", chapter=2, description="当前事件", causes=["ev-future"]),
    )

    assert issues


def test_summary_manager_generates_rolling_context() -> None:
    story = Story(title="测试", premise="摘要测试")
    manager = SummaryManager()
    manager.generate_chapter_summary(story, 1, "主角发现秘密。随后他决定离开城市。")
    manager.generate_volume_summary(story, 1, [1])

    context = manager.get_rolling_context(story, 2)

    assert "第1章" in context
    assert "当前卷概览" in context


def test_pacing_analyzer_warns_on_flat_trend() -> None:
    analyzer = PacingAnalyzer()
    analyses = [analyzer.analyze_chapter("他看着天空。\n风很安静。") for _ in range(3)]

    assert "预警" in analyzer.check_pacing_trend(analyses)


def test_character_state_tracker_updates_current_state() -> None:
    story = Story(title="测试", premise="人物状态")
    character = Character(id="hero", name="王绍康")
    story.characters[character.id] = character
    tracker = CharacterStateTracker()

    states = tracker.extract_state_from_chapter(story, 1, "王绍康在球场发现自己能预判射门。", [character])

    assert states
    assert tracker.get_current_state(story, "hero").location == "球场"


def test_longform_manager_processes_new_chapter() -> None:
    story = Story(title="测试", premise="长篇增强")
    story.characters["hero"] = Character(id="hero", name="主角")
    manager = LongformManager(MockLLMClient())

    result = manager.process_new_chapter(
        story,
        1,
        "主角在球场发现一枚神秘钥匙。他意识到这件事背后藏着真相。",
    )

    assert result["summary"]
    assert story.chapter_summaries[1]
    assert story.causal_events
    assert story.foreshadowings
    assert story.character_states["hero"]
