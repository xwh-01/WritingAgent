from __future__ import annotations

import json

from novelforge.agents.planner import PlannerAgent
from novelforge.domain import ChapterContract, ChapterOutline
from novelforge.llm.base import LLMClient


class ScriptedLLM(LLMClient):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def chat_completion(self, messages, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def valid_beat(**overrides) -> dict:
    beat = {
        "scene_index": 1,
        "description": "进入档案室",
        "goal": "找到证词",
        "outcome": "找到证词",
        "title": "档案室",
        "purpose": "迫使主角选择",
        "pov_character": "林砚",
        "location": "档案室",
        "time_context": "午夜前",
        "participating_characters": ["林砚"],
        "character_goals": {"林砚": "找到证词"},
        "conflict": "档案即将封存",
        "obstacle": "门禁失效",
        "must_happen": ["发现证词"],
        "must_not_happen": [],
        "information_revealed": ["父亲参与旧案"],
        "start_state": {"location": "走廊"},
        "end_state": {"location": "档案室"},
        "transition_to_next": "",
        "target_length": 600,
        "content": "",
        "status": "planned",
    }
    beat.update(overrides)
    return beat


def test_planner_repairs_invalid_provider_field_types_once() -> None:
    invalid = valid_beat(
        information_revealed="父亲参与旧案",
        start_state="林砚在走廊",
        end_state="林砚进入档案室",
    )
    repaired = valid_beat()
    llm = ScriptedLLM(
        [
            json.dumps([invalid], ensure_ascii=False),
            json.dumps([repaired], ensure_ascii=False),
        ]
    )

    beats = PlannerAgent(llm).generate_beats(
        ChapterOutline(
            chapter_index=1,
            title="雨夜",
            summary="寻找证词",
            conflict="档案即将封存",
        ),
        target_length=600,
    )

    assert llm.calls == 2
    assert beats[0].information_revealed == ["父亲参与旧案"]
    assert beats[0].start_state == {"location": "走廊"}


def test_planner_retries_when_the_first_json_repair_is_truncated() -> None:
    invalid = valid_beat(information_revealed="父亲参与旧案")
    repaired = valid_beat()
    llm = ScriptedLLM(
        [
            json.dumps([invalid], ensure_ascii=False),
            "[{\"scene_index\": 1}",
            json.dumps([repaired], ensure_ascii=False),
        ]
    )

    beats = PlannerAgent(llm).generate_beats(
        ChapterOutline(chapter_index=1, title="雨夜", summary="寻找证词", conflict="档案即将封存"),
        target_length=600,
    )

    assert llm.calls == 3
    assert beats[0].information_revealed == ["父亲参与旧案"]


def test_planner_normalizes_empty_optional_scene_fields_without_a_repair_call() -> None:
    llm = ScriptedLLM([json.dumps([{"scene_index": 1}], ensure_ascii=False)])
    outline = ChapterOutline(
        chapter_index=1,
        title="测试章",
        summary="主角必须推进关键冲突",
        conflict="门禁即将关闭",
        pov_character="林砚",
    )

    beats = PlannerAgent(llm).generate_beats(
        outline,
        contract=ChapterContract(chapter_index=1, pov_character="林砚"),
        target_length=600,
    )

    assert llm.calls == 1
    assert beats[0].purpose == "主角必须推进关键冲突"
    assert beats[0].character_goals == {"林砚": "主角必须推进关键冲突"}
    assert beats[0].obstacle == "门禁即将关闭"
    assert beats[0].outcome
