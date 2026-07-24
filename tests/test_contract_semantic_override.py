from __future__ import annotations

import json

from novelforge.domain import ChapterContract
from novelforge.llm.base import LLMClient
from novelforge.validation.contract import ChapterContractValidator


class SemanticLLM(LLMClient):
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    def chat_completion(self, messages, **kwargs):
        return json.dumps(self.items, ensure_ascii=False)


def test_cited_semantic_pass_can_override_lexical_miss_for_required_event() -> None:
    requirement = "林砚将原始证词交给监察官并承担公开代价"
    llm = SemanticLLM(
        [
            {
                "constraint_type": "must_happen",
                "requirement": requirement,
                "passed": True,
                "confidence": 0.95,
                "evidence": "他把泛黄纸页推过桌面，门外记者的闪光灯同时亮起。",
                "paragraph_range": "段落4",
                "explanation": "交付与公开后果均已通过同义场景完成。",
            }
        ]
    )
    contract = ChapterContract(chapter_index=1, must_happen=[requirement])
    content = "他把泛黄纸页推过桌面。\n\n门外记者的闪光灯同时亮起。"

    check = ChapterContractValidator(llm).validate(content, contract)[0]

    assert check.rule_passed is False
    assert check.semantic_passed is True
    assert check.passed is True
    assert str(check.status) == "passed"


def test_semantic_override_requires_cited_evidence() -> None:
    requirement = "林砚将原始证词交给监察官"
    llm = SemanticLLM(
        [
            {
                "constraint_type": "must_happen",
                "requirement": requirement,
                "passed": True,
                "confidence": 0.95,
                "evidence": "",
                "paragraph_range": "",
                "explanation": "已完成",
            }
        ]
    )
    contract = ChapterContract(chapter_index=1, must_happen=[requirement])

    check = ChapterContractValidator(llm).validate("他递出纸页。", contract)[0]

    assert check.passed is False
    assert str(check.status) == "review_required"


def test_forbidden_future_threat_is_not_mistaken_for_the_forbidden_event() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["敌军提前兵临城下"])

    check = ChapterContractValidator().validate_fast(
        "斥候报告敌军前锋仍在青石渡，最早三天后才会兵临城下。",
        contract,
    )[0]

    assert check.passed is True
    assert str(check.status) == "passed"


def test_forbidden_specific_situation_detects_concrete_operational_details() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["不能出现弟弟的具体情况或外勤任务细节（留待后续展开）"],
    )

    check = ChapterContractValidator().validate_fast(
        "魏衡说：你弟弟所在的外勤组还有四十分钟返航，气压服依赖主回路。",
        contract,
    )[0]

    assert check.passed is False
    assert str(check.status) == "failed"
    assert "外勤组" in check.evidence


def test_forbidden_actual_action_does_not_match_an_order_to_act() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["沈砚实际开始修复玻璃"])

    check = ChapterContractValidator().validate_fast(
        "罗禾要求沈砚立刻修复玻璃，沈砚却把手停在裂痕上方。",
        contract,
    )[0]

    assert check.passed is True


def test_forbidden_actual_repair_detects_core_component_disassembly() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["阿洛在本章内实际修复阀门"],
    )

    check = ChapterContractValidator().validate_fast(
        "阿洛拆下主阀的第一颗螺栓，取出变形垫圈放进样品袋。",
        contract,
    )[0]

    assert check.passed is False
    assert str(check.status) == "failed"
    assert "拆下" in check.evidence


def test_forbidden_direct_dialogue_detects_an_actual_channel_exchange() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["魏星（外勤舱）在章节内返回基地或与阿洛直接对话"],
    )

    check = ChapterContractValidator().validate_fast(
        "阿洛按下外勤频道的呼叫键。魏星的声音传来：‘正在回收样本。’",
        contract,
    )[0]

    assert check.passed is False
    assert str(check.status) == "failed"
    assert "魏星" in check.evidence


def test_forbidden_final_choice_detects_an_explicit_committed_outcome() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["周岚在章节内做出播出或封存的最终决定"],
    )

    check = ChapterContractValidator().validate_fast(
        "周岚决定不按下播出按钮，把磁带封存进抽屉。",
        contract,
    )[0]

    assert check.passed is False
    assert str(check.status) == "failed"


def test_forbidden_alternative_plan_detects_commander_delegating_the_decision() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["魏衡改变决定或提供替代方案"],
    )

    check = ChapterContractValidator().validate_fast(
        "魏衡看着阿洛说：‘复位还是不复位，你定。’",
        contract,
    )[0]

    assert check.passed is False


def test_forbidden_hiding_detects_concrete_concealment_alias() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["林砚直接销毁或藏匿证词"])

    check = ChapterContractValidator().validate_fast(
        "林砚把证词对折，塞进工作服内袋。",
        contract,
    )[0]

    assert check.passed is False
    assert "内袋" in check.evidence


def test_forbidden_lack_of_empathy_detects_protective_action() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["罗禾表现出对沈砚处境的深刻理解"])

    check = ChapterContractValidator().validate_fast(
        "罗禾按住城门的裂缝，替沈砚争取时间看清记忆。",
        contract,
    )[0]

    assert check.passed is False
    assert "争取时间" in check.evidence


def test_forbidden_full_disclosure_detects_quoted_document_details() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_not_happen=["揭示调解书全部细节或旧债全貌"],
    )

    check = ChapterContractValidator().validate_fast(
        "调解书上写着：“乙方许建国之女许知夏，自愿承担全部拆迁补偿债务。”",
        contract,
    )[0]

    assert check.passed is False
    assert "调解书" in check.evidence
