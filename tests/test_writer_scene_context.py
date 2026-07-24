from __future__ import annotations

import json

from novelforge.agents.writer import WriterAgent
from novelforge.domain import Beat, ChapterContract


class _RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def chat_completion(self, messages, **kwargs) -> str:
        self.systems.append(messages[0]["content"])
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if "scene_end_state_reconcile" in prompt:
            return json.dumps(
                {
                    "location_changes": {"林砚": "黑曜门内"},
                    "knowledge_gained": {"林砚": ["旧钟开启机关"]},
                    "ending_state": {"source": "final_prose"},
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "content": "林砚把月纹钥匙贴上黑曜门，旧钟在掌心发烫。",
                "ending_state": {"location_changes": {"林砚": "门外"}},
            },
            ensure_ascii=False,
        )


def _scene() -> Beat:
    return Beat(
        scene_index=1,
        title="开门",
        purpose="兑现承诺",
        goal="打开黑曜门",
        outcome="机关被启动",
        obstacle="钥匙会暴露秘密",
        participating_characters=["林砚"],
        character_goals={"林砚": "守住钥匙"},
    )


def test_writer_receives_traceable_scene_context_and_reconciles_final_prose() -> None:
    llm = _RecordingLLM()
    writer = WriterAgent(llm)
    scene = _scene()
    draft = writer.write_scene(
        story_premise="守门人必须保护钥匙。",
        contract=ChapterContract(chapter_index=30),
        scene=scene,
        previous_scene_end_state=None,
        character_states={},
        style_requirements="克制",
        forbidden_actions=[],
        scene_context="[待处理伏笔 | 来源: 第1章正式正文 | 入选原因: 避免提前泄露]\n月纹钥匙对应黑曜门机关。",
        scene_obligations=[
            {
                "id": "ending",
                "constraint_type": "ending_hook",
                "requirement": "林砚的手停在门锁上",
                "mode": "must_end_with",
            }
        ],
        previous_scene_obligations=[
            {
                "id": "recording",
                "constraint_type": "must_happen",
                "requirement": "林砚已经拿到钥匙",
                "mode": "must_include",
            }
        ],
    )
    end_state = writer.reconcile_scene_end_state(
        content="林砚带着旧钟走进黑曜门内。",
        scene=scene,
        previous_scene_end_state=draft.ending_state,
    )

    assert "SCENE_CANONICAL_CONTEXT" in llm.prompts[0]
    assert "月纹钥匙对应黑曜门机关" in llm.prompts[0]
    assert "来源: 第1章正式正文" in llm.prompts[0]
    assert "SCENE_CONTRACT_OBLIGATIONS" in llm.prompts[0]
    assert "林砚的手停在门锁上" in llm.prompts[0]
    assert "CONTRACT_EXECUTION_CHECKLIST" in llm.systems[0]
    assert "林砚的手停在门锁上" in llm.systems[0]
    assert "PREVIOUS_SCENE_OBLIGATIONS" in llm.prompts[0]
    assert "林砚已经拿到钥匙" in llm.prompts[0]
    assert "final_content=林砚带着旧钟走进黑曜门内。" in llm.prompts[1]
    assert end_state.location_changes["林砚"] == "黑曜门内"
    assert end_state.ending_state["source"] == "final_prose"


def test_writer_recovers_typographic_json_quotes_without_a_repair_call() -> None:
    class CurlyQuoteLLM:
        def chat_completion(self, _messages, **_kwargs) -> str:
            return '{“content”: “林砚停在门锁前。”, “ending_state”: {}}'

    draft = WriterAgent(CurlyQuoteLLM()).write_scene(
        story_premise="测试",
        contract=ChapterContract(chapter_index=1),
        scene=_scene(),
        previous_scene_end_state=None,
        character_states={},
        style_requirements="",
        forbidden_actions=[],
    )

    assert draft.content == "林砚停在门锁前。"


def test_writer_recovers_prose_when_only_the_trailing_state_json_is_malformed() -> None:
    class MalformedStateLLM:
        def chat_completion(self, _messages, **_kwargs) -> str:
            return '{"content":"林砚把证词递到监察登记窗口。","ending_state":{"decisions":{},}}'

    draft = WriterAgent(MalformedStateLLM()).write_scene(
        story_premise="测试",
        contract=ChapterContract(chapter_index=1),
        scene=_scene(),
        previous_scene_end_state=None,
        character_states={},
        style_requirements="",
        forbidden_actions=[],
    )

    assert draft.content == "林砚把证词递到监察登记窗口。"
    assert draft.ending_state.characters_present == ["林砚"]


def test_writer_promotes_negative_parts_of_required_events_to_hard_conditions() -> None:
    llm = _RecordingLLM()
    WriterAgent(llm).write_scene(
        story_premise="测试",
        contract=ChapterContract(chapter_index=1, must_happen=["林砚拿住证词，没有塞进口袋"]),
        scene=_scene(),
        previous_scene_end_state=None,
        character_states={},
        style_requirements="",
        forbidden_actions=[],
    )

    assert "NEGATIVE_CONDITIONS" in llm.systems[0]
    assert "没有塞进口袋" in llm.systems[0]
