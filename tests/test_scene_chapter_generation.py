from __future__ import annotations

import json
import re

import pytest

from novelforge.agents.planner import PlannerAgent
from novelforge.agents.writer import WriterAgent
from novelforge.core.exceptions import WorkflowError
from novelforge.core.models import Beat, Chapter, ChapterContract, ChapterOutline, SceneEndState, Story
from novelforge.llm.mock_client import MockLLMClient
from novelforge.orchestrator.engine import NovelForgeEngine


def scene_plan(index: int, *, start_state: dict | None = None) -> dict:
    return {
        "scene_index": index,
        "title": f"Scene {index}",
        "purpose": f"Distinct purpose {index}",
        "pov_character": "Hero",
        "location": "hall",
        "time_context": f"2026-01-01T0{index}:00:00",
        "participating_characters": ["Hero"],
        "character_goals": {"Hero": f"goal {index}"},
        "conflict": f"conflict {index}",
        "obstacle": f"obstacle {index}",
        "must_happen": [f"event {index}"],
        "must_not_happen": [],
        "information_revealed": [f"clue {index}"],
        "start_state": start_state or {},
        "end_state": {},
        "transition_to_next": "continue" if index == 1 else "",
        "target_length": 900,
        "description": f"description {index}",
        "goal": f"goal {index}",
        "outcome": f"result {index}",
        "content": "",
        "status": "planned",
    }


class FakeSceneLLM(MockLLMClient):
    def __init__(self, *, fail_scene: int | None = None, on_scene=None) -> None:
        self.fail_scene = fail_scene
        self.on_scene = on_scene
        self.scene_prompts: list[tuple[int, str]] = []

    def chat_completion(self, messages: list[dict[str, str]], **kwargs) -> str:
        prompt = "\n".join(message.get("content", "") for message in messages)
        if "generate_beats" in prompt:
            return json.dumps([scene_plan(1), scene_plan(2)])
        if "CURRENT_SCENE" in prompt and "PREVIOUS_SCENE_END_STATE" in prompt:
            current_section = prompt.split("CURRENT_SCENE", 1)[1].split("PREVIOUS_SCENE_END_STATE", 1)[0]
            index = int(re.search(r'"scene_index"\s*:\s*(\d+)', current_section).group(1))
            self.scene_prompts.append((index, prompt))
            if self.on_scene:
                self.on_scene(index)
            if self.fail_scene == index:
                return "not-json"
            return json.dumps(
                {
                    "content": f"scene-{index}-content",
                    "ending_state": {
                        "characters_present": ["Hero"],
                        "character_state_changes": {"Hero": f"changed-{index}"},
                        "relationship_changes": [],
                        "location_changes": {"Hero": "hall"},
                        "time_changes": f"2026-01-01T0{index}:30:00",
                        "knowledge_gained": {"Hero": [f"clue-{index}"]},
                        "items_gained": {},
                        "items_lost": {},
                        "injuries_or_conditions": {},
                        "decisions": {"Hero": f"decision-{index}"},
                        "promises": [],
                        "questions_created": [],
                        "questions_resolved": [],
                        "ending_state": {"scene": index},
                    },
                }
            )
        return super().chat_completion(messages, **kwargs)


def prepared_engine(test_config, llm: FakeSceneLLM) -> NovelForgeEngine:
    test_config.story.auto_polish_drafts = False
    engine = NovelForgeEngine(test_config)
    story = engine.start_new_story("premise", title="Scenes", style_guide="restrained")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="Chapter", summary="chapter goal", conflict="pressure", pov_character="Hero")
    ]
    story.content.chapter_contracts[1] = ChapterContract(
        chapter_index=1,
        pov_character="Hero",
        ending_hook="a final hook",
    )
    engine.planner = PlannerAgent(llm)
    engine.writer = WriterAgent(llm)
    return engine


def test_legacy_beat_loads_and_new_fields_serialize() -> None:
    old_story = Story.model_validate(
        {
            "title": "Legacy",
            "premise": "old json",
            "chapters": {
                "1": {
                    "index": 1,
                    "title": "Old",
                    "beats": [
                        {"scene_index": 1, "description": "legacy", "goal": "find clue", "outcome": "clue found"}
                    ],
                }
            },
        }
    )
    legacy = old_story.content.chapters[1].beats[0]
    assert legacy.title == ""
    assert legacy.character_goals == {}
    assert legacy.content == ""
    serialized = Beat.model_validate(scene_plan(2)).model_dump()
    assert serialized["purpose"] == "Distinct purpose 2"
    assert serialized["target_length"] == 900
    assert serialized["status"] == "planned"


def test_planner_returns_ordered_structured_scenes() -> None:
    story = Story(title="Story", premise="premise")
    outline = ChapterOutline(chapter_index=1, title="One", summary="goal", conflict="conflict")
    scenes = PlannerAgent(FakeSceneLLM()).generate_beats(
        outline,
        story=story,
        contract=ChapterContract(chapter_index=1),
        target_length=1800,
    )
    assert [scene.scene_index for scene in scenes] == [1, 2]
    assert all(scene.character_goals and scene.obstacle and scene.outcome for scene in scenes)
    assert sum(scene.target_length for scene in scenes) == 1800


def test_writer_runs_in_order_passes_end_state_merges_and_updates_memory_once(test_config, monkeypatch) -> None:
    memory_calls: list[str] = []
    llm = FakeSceneLLM(on_scene=lambda _index: memory_calls and pytest.fail("memory updated mid-chapter"))
    engine = prepared_engine(test_config, llm)
    monkeypatch.setattr(engine, "_process_chapter_memory", lambda _story, chapter: memory_calls.append(chapter.content))

    chapter = engine.write_chapter(1)

    assert [index for index, _prompt in llm.scene_prompts] == [1, 2]
    assert '"scene": 1' in llm.scene_prompts[1][1]
    assert chapter.content == "scene-1-content\n\n***\n\nscene-2-content"
    assert [scene.content for scene in chapter.beats] == ["scene-1-content", "scene-2-content"]
    assert all(scene.status == "completed" for scene in chapter.beats)
    assert memory_calls == [chapter.content]


def test_location_conflict_is_detected(test_config) -> None:
    engine = NovelForgeEngine(test_config)
    previous = SceneEndState(location_changes={"Hero": "station"})
    current = Beat.model_validate(scene_plan(2, start_state={"character_locations": {"Hero": "harbor"}}))

    with pytest.raises(WorkflowError, match="location conflict.*Hero"):
        engine._validate_scene_transition(previous, current)


def test_lost_item_reappearance_is_detected(test_config) -> None:
    engine = NovelForgeEngine(test_config)
    previous = SceneEndState(items_lost={"Hero": ["key"]})
    current = Beat.model_validate(scene_plan(2, start_state={"inventory": {"Hero": ["key"]}}))

    with pytest.raises(WorkflowError, match="lost item conflict.*key"):
        engine._validate_scene_transition(previous, current)


def test_mid_scene_failure_keeps_old_chapter_and_skips_memory(test_config, monkeypatch) -> None:
    llm = FakeSceneLLM(fail_scene=2)
    engine = prepared_engine(test_config, llm)
    old = Chapter(index=1, title="Old", content="official old chapter", version=7, status="revised")
    engine.story.content.chapters[1] = old
    memory_calls: list[int] = []
    monkeypatch.setattr(engine, "_process_chapter_memory", lambda *_args: memory_calls.append(1))

    with pytest.raises(WorkflowError, match="Scene 2 generation failed"):
        engine.write_chapter(1)

    assert engine.story.content.chapters[1] is old
    assert old.content == "official old chapter"
    assert old.version == 7
    assert memory_calls == []


def test_writer_prompt_has_required_sections() -> None:
    llm = FakeSceneLLM()
    WriterAgent(llm).write_scene(
        story_premise="premise",
        contract=ChapterContract(chapter_index=1),
        scene=Beat.model_validate(scene_plan(1)),
        previous_scene_end_state=None,
        character_states={},
        style_requirements="style",
        forbidden_actions=["forbidden"],
    )
    prompt = llm.scene_prompts[0][1]
    for section in (
        "STORY_PREMISE",
        "CHAPTER_CONTRACT",
        "CURRENT_SCENE",
        "PREVIOUS_SCENE_END_STATE",
        "CHARACTER_STATES",
        "STYLE_REQUIREMENTS",
        "FORBIDDEN_ACTIONS",
        "OUTPUT_REQUIREMENTS",
    ):
        assert section in prompt
