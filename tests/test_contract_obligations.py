from __future__ import annotations

from novelforge.domain import Beat, ChapterContract, CheckStatus, ConstraintCheck
from novelforge.validation import ContractObligationCompiler


def _beats() -> list[Beat]:
    return [
        Beat(
            scene_index=1,
            title="录音",
            purpose="发现姐姐求救录音",
            goal="确认信号",
            outcome="知道船将离港",
            participating_characters=["周岚"],
            character_goals={"周岚": "确认录音"},
            information_revealed=["姐姐求救录音"],
        ),
        Beat(
            scene_index=2,
            title="红色开关",
            purpose="在规程和救人间选择",
            goal="决定是否播出",
            outcome="手停在播出开关上",
            participating_characters=["周岚", "顾宁"],
            character_goals={"周岚": "做出决定"},
            must_happen=["周岚的手放在播出开关上"],
        ),
    ]


def test_compiler_assigns_contract_work_to_scenes_and_keeps_forbidden_rules_global() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_happen=["周岚收到姐姐的求救录音"],
        must_not_happen=["周岚被当场开除"],
        knowledge_boundaries={"周岚": {"可以获得": ["姐姐求救录音"]}},
        ending_hook="周岚的手放在播出开关上",
    )

    plan = ContractObligationCompiler().compile(contract, _beats())

    assert plan.is_executable
    assert [item.scene_index for item in plan.obligations if item.constraint_type == "must_happen"] == [1]
    assert [item.scene_index for item in plan.obligations if item.constraint_type == "ending_hook"] == [2]
    assert len([item for item in plan.obligations if item.constraint_type == "must_not_happen"]) == 2
    assert any(item.constraint_type == "knowledge_acquisition" for item in plan.obligations)


def test_compiler_rejects_action_that_is_both_required_and_forbidden() -> None:
    contract = ChapterContract(
        chapter_index=1,
        must_happen=["沈砚修复玻璃"],
        must_not_happen=["沈砚在第一章就修复玻璃"],
    )

    plan = ContractObligationCompiler().compile(contract, _beats())

    assert not plan.is_executable
    assert plan.conflicts[0].code == "required_forbidden_overlap"


def test_evidence_ledger_maps_failed_check_back_to_the_planned_scene() -> None:
    contract = ChapterContract(chapter_index=1, must_happen=["周岚收到姐姐的求救录音"])
    compiler = ContractObligationCompiler()
    plan = compiler.compile(contract, _beats())
    requirement = contract.must_happen[0]
    ledger = compiler.build_ledger(
        plan,
        [
            ConstraintCheck(
                constraint_type="must_happen",
                requirement=requirement,
                passed=False,
                status=CheckStatus.FAILED,
                message="missing",
            )
        ],
    )

    assert len(ledger.failed_entries) == 1
    assert ledger.failed_entries[0].scene_index == 1
    assert ledger.failed_entries[0].failure_category == "missing_required_event"


def test_forbidden_action_evidence_targets_only_the_scene_that_contains_it() -> None:
    contract = ChapterContract(chapter_index=1, must_not_happen=["周岚被当场开除"])
    beats = _beats()
    beats[1].content = "顾宁宣布周岚被当场开除。"
    compiler = ContractObligationCompiler()
    plan = compiler.compile(contract, beats)
    ledger = compiler.build_ledger(
        plan,
        [
            ConstraintCheck(
                constraint_type="must_not_happen",
                requirement="周岚被当场开除",
                passed=False,
                status=CheckStatus.FAILED,
                evidence="顾宁宣布周岚被当场开除。",
                paragraph_range="段落2",
            )
        ],
        beats,
    )

    assert [item.scene_index for item in ledger.failed_entries] == [2]


def test_compiler_normalizes_fact_key_knowledge_boundaries() -> None:
    contract = ChapterContract(
        chapter_index=1,
        knowledge_boundaries={
            "阿洛": {
                "知道氧气危机": ["true"],
                "不知弟弟当前状况": [],
            }
        },
    )

    plan = ContractObligationCompiler().compile(contract, _beats())
    requirements = {
        item.requirement
        for item in plan.obligations
        if item.constraint_type in {"knowledge_boundary", "knowledge_acquisition"}
    }

    assert "阿洛 应已知道: 氧气危机" in requirements
    assert "阿洛 不应知道: 弟弟当前状况" in requirements
    assert all("true" not in item for item in requirements)
