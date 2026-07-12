from __future__ import annotations

import json

from novelforge.core.models import ChapterContract
from novelforge.llm.base import LLMClient
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.validation import ChapterContractValidator


class SemanticLLM(LLMClient):
    def __init__(self, passed: bool, confidence: float) -> None:
        self.passed = passed
        self.confidence = confidence

    def chat_completion(self, messages, **kwargs) -> str:
        prompt = messages[-1]["content"]
        requirement = "林默发现未来车票"
        return json.dumps([{
            "constraint_type": "must_happen",
            "requirement": requirement,
            "passed": self.passed,
            "confidence": self.confidence,
            "evidence": "车票日期来自三年后",
            "paragraph_range": "段落1",
            "explanation": "正文以同义表达完成了发现。",
        }], ensure_ascii=False)


class InvalidSemanticLLM(LLMClient):
    def chat_completion(self, messages, **kwargs) -> str:
        return "not-json"


def test_contract_validator_checks_required_forbidden_and_ending() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_happen=["林默发现未来车票"],
        must_not_happen=["苏晴公开真实身份"],
        ending_hook="广播响起林默的声音",
    )
    content = "林默翻开掌心，终于发现那张未来车票。\n\n夜色压住站台。广播忽然响起林默的声音。"

    checks = ChapterContractValidator().validate(content, contract)

    assert [check.passed for check in checks] == [True, True, True]
    assert ChapterContractValidator().hard_constraints_passed(checks) is True


def test_contract_validator_blocks_forbidden_event() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["苏晴公开真实身份"])

    checks = ChapterContractValidator().validate("苏晴公开真实身份，承认了一切。", contract)

    assert checks[0].passed is False
    assert ChapterContractValidator().hard_constraints_passed(checks) is False


def test_engine_creates_and_persists_contract(test_config) -> None:
    engine = NovelForgeEngine(test_config)
    story = engine.start_new_story("失忆铸剑师寻找过去", title="合同测试")
    engine.generate_outline(1)

    contract = engine.ensure_chapter_contract(1)
    contract.must_not_happen.append("主角死亡")
    engine.update_chapter_contract(1, contract)

    assert story.content.chapter_contracts[1].must_not_happen == ["主角死亡"]


def test_semantic_validation_adds_evidence_when_both_judges_agree() -> None:
    contract = ChapterContract(chapter_index=1, must_happen=["林默发现未来车票"])
    validator = ChapterContractValidator(SemanticLLM(True, 0.92))

    check = validator.validate("林默发现未来车票，日期竟来自三年后。", contract)[0]

    assert check.passed is True
    assert check.status == "passed"
    assert check.validation_method == "rule+llm"
    assert check.confidence == 0.92
    assert check.evidence == "车票日期来自三年后"
    assert check.paragraph_range == "段落1"


def test_semantic_conflict_requires_manual_review() -> None:
    contract = ChapterContract(chapter_index=1, must_happen=["林默发现未来车票"])
    validator = ChapterContractValidator(SemanticLLM(True, 0.9))

    check = validator.validate("他盯着纸片上的年份，脸色骤然发白。", contract)[0]

    assert check.rule_passed is False
    assert check.semantic_passed is True
    assert check.passed is False
    assert check.status == "review_required"
    assert validator.hard_constraints_passed([check]) is False


def test_low_semantic_confidence_requires_manual_review() -> None:
    contract = ChapterContract(chapter_index=1, must_happen=["林默发现未来车票"])
    check = ChapterContractValidator(SemanticLLM(True, 0.4)).validate(
        "林默发现未来车票。", contract
    )[0]

    assert check.status == "review_required"
    assert "置信度" in check.message


def test_invalid_semantic_response_falls_back_to_rule_result() -> None:
    contract = ChapterContract(chapter_index=1, must_happen=["林默发现未来车票"])

    check = ChapterContractValidator(InvalidSemanticLLM()).validate(
        "林默发现未来车票。", contract
    )[0]

    assert check.passed is True
    assert check.status == "passed"
    assert check.validation_method == "rule"
    assert check.semantic_passed is None
