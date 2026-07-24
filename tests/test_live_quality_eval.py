from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from evals import live_quality
from evals.live_fixtures import fixed_case_plan
from evals.live_quality import (
    CASES_DIR,
    CandidateScore,
    JudgeDecision,
    LiveCase,
    _judge_prompt,
    resolve_pair,
    summarize,
)
from novelforge.llm.base import LLMResponse


def decision(winner: str) -> JudgeDecision:
    score = CandidateScore(
        plot_progression=8,
        character_fidelity=8,
        continuity=8,
        scene_quality=8,
        prose_quality=8,
    )
    return JudgeDecision(
        winner=winner,
        scores={"A": score, "B": score},
        hard_failures={"A": [], "B": []},
        reason="evidence",
    )


def test_swapped_blind_judges_resolve_treatment_without_position_bias() -> None:
    pair = resolve_pair(decision("B"), decision("A"))

    assert pair.resolved_winner == "treatment"
    assert pair.consistent is True


def test_order_disagreement_is_uncertain() -> None:
    pair = resolve_pair(decision("B"), decision("B"))

    assert pair.resolved_winner == "uncertain"
    assert pair.consistent is False


def test_tie_and_one_directional_win_are_order_compatible() -> None:
    pair = resolve_pair(decision("TIE"), decision("A"))

    assert pair.resolved_winner == "tie"
    assert pair.consistent is True
    assert pair.consistency_mode == "tie_tolerant"


def test_small_sample_cannot_claim_improvement() -> None:
    trials = [
        {"pair_decision": {"resolved_winner": "treatment", "consistent": True}}
    ]

    assert summarize(trials)["verdict"] == "insufficient_evidence"


def test_live_suite_defaults_to_three_repetitions() -> None:
    assert inspect.signature(live_quality.run_suite).parameters["repetitions"].default == 3


def test_order_sensitive_trials_do_not_become_zero_percent_quality_wins() -> None:
    summary = summarize(
        [
            {"pair_decision": {"resolved_winner": "uncertain", "consistent": False}}
            for _ in range(3)
        ]
    )

    assert summary["treatment_win_rate"] is None
    assert summary["order_consistency_rate"] == 0.0


def test_three_consistent_wins_are_conclusive() -> None:
    trials = [
        {"pair_decision": {"resolved_winner": "treatment", "consistent": True}}
        for _ in range(3)
    ]

    assert summarize(trials)["verdict"] == "treatment_better"


def test_summary_reports_hard_constraint_and_generation_cost_deltas() -> None:
    trials = [
        {
            "pair_decision": {"resolved_winner": "treatment", "consistent": True},
            "baseline": {
                "judge_hard_constraints_passed": True,
                "call_metrics": {"calls": 1, "total_tokens": 100, "latency_ms": 80},
            },
            "treatment": {
                "judge_hard_constraints_passed": True,
                "accepted_by_internal_gate": True,
                "all_hard_constraints_passed": True,
                "candidate_selections": [{"scene_index": 1, "selected_id": "scene-a"}],
                "budget": {"exhausted_reason": ""},
                "call_metrics": {"calls": 4, "total_tokens": 400, "latency_ms": 300},
                "attempts": [
                    {
                        "review_mode": "unified",
                        "failure_categories": ["missing_required_event"],
                    }
                ],
            },
        }
        for _ in range(3)
    ]

    summary = summarize(trials)

    assert summary["hard_constraint_pass_rates"]["treatment_all"] == 1.0
    assert summary["average_generation_call_metrics"]["treatment_minus_baseline"]["calls"] == 3
    assert summary["average_generation_call_metrics"]["treatment_minus_baseline"]["total_tokens"] == 300
    assert summary["review_mode_counts"]["unified"] == 3
    assert summary["failure_categories"]["missing_required_event"] == 3
    assert summary["quality_search"] == {
        "selected_scene_count": 3,
        "trials_with_selection": 3,
        "budget_exhausted_trials": 0,
    }


def test_summary_preserves_provider_failures_without_claiming_improvement() -> None:
    summary = summarize(
        [
            {
                "trial": 1,
                "case_id": "sealed_signal",
                "status": "failed",
                "error_type": "ProviderError",
                "error": "insufficient balance",
            }
        ]
    )

    assert summary["trials"] == 0
    assert summary["failed_trials"] == 1
    assert summary["verdict"] == "insufficient_evidence"
    assert summary["execution_failures"][0]["error_type"] == "ProviderError"
    assert summary["treatment_win_rate"] is None
    assert summary["order_consistency_rate"] is None
    assert summary["hard_constraint_pass_rates"]["treatment_all"] is None


def test_live_suite_has_diverse_real_provider_cases() -> None:
    paths = sorted(Path(CASES_DIR).glob("*.json"))
    cases = [LiveCase.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]

    assert len(cases) >= 6
    assert len({item.id for item in cases}) == len(cases)
    assert {"现实悬疑", "奇幻", "都市情感", "科幻", "现实主义"}.issubset(
        {item.genre for item in cases}
    )
    assert all(fixed_case_plan(item.id) is not None for item in cases)


def test_resume_appends_trials_and_rebuilds_a_combined_summary(tmp_path, monkeypatch) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    case = LiveCase(id="case", title="题目", premise="前提")
    (cases_dir / "case.json").write_text(case.model_dump_json(), encoding="utf-8")
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    (output_dir / "case-1.json").write_text(
        json.dumps({"case_id": "case", "trial": 1, "pair_decision": {"resolved_winner": "treatment", "consistent": True}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        live_quality,
        "load_config",
        lambda _path: SimpleNamespace(llm=SimpleNamespace(provider="deepseek", model="deepseek-chat", temperature=0.8)),
    )
    monkeypatch.setattr(
        live_quality,
        "run_trial",
        lambda _case, _config, index: {
            "case_id": "case",
            "trial": index,
            "pair_decision": {"resolved_winner": "treatment", "consistent": True},
        },
    )

    destination = live_quality.run_suite(
        cases_dir=cases_dir,
        output_dir=output_dir,
        repetitions=1,
        resume=True,
    )

    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))["summary"]
    assert (destination / "case-2.json").is_file()
    assert summary["trials"] == 2
    assert summary["attempted_trials"] == 2


def test_recompute_saved_summary_keeps_raw_trials_and_applies_current_protocol(tmp_path) -> None:
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    first = decision("TIE").model_dump()
    second = decision("A").model_dump()
    raw = {
        "case_id": "case",
        "trial": 1,
        "baseline": {"judge_hard_constraints_passed": True},
        "treatment": {"accepted_by_internal_gate": True},
        "blind_judges": [
            {"order": "baseline,treatment", "decision": first},
            {"order": "treatment,baseline", "decision": second},
        ],
    }
    raw_path = output_dir / "case-1.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    destination = live_quality.recompute_saved_summary(output_dir)
    report = json.loads(destination.read_text(encoding="utf-8"))

    assert raw_path.is_file()
    assert report["aggregation_protocol"] == "swapped_order_v2_corroborated_hard_failures"
    assert report["summary"]["order_consistency_rate"] == 1.0


def test_judge_repairs_one_malformed_provider_response() -> None:
    valid = json.dumps(
        {
            "winner": "A",
            "scores": {
                "A": {"plot_progression": 8, "character_fidelity": 8, "continuity": 8, "scene_quality": 8, "prose_quality": 8},
                "B": {"plot_progression": 7, "character_fidelity": 7, "continuity": 7, "scene_quality": 7, "prose_quality": 7},
            },
            "hard_failures": {"A": [], "B": []},
            "reason": "evidence",
        }
    )

    class SequencedClient:
        def __init__(self) -> None:
            self.responses = iter([LLMResponse(content='{"winner":"A"'), LLMResponse(content=valid)])

        def chat_completion_result(self, *_args, **_kwargs) -> LLMResponse:
            return next(self.responses)

    result, calls = live_quality._judge(  # noqa: SLF001 - verifies evaluator recovery boundary
        SequencedClient(),
        LiveCase(id="case", title="题目", premise="前提"),
        {},
        {},
        "正文 A",
        "正文 B",
    )

    assert result.winner == "A"
    assert len(calls) == 2


def test_judge_prompt_treats_must_not_as_a_prohibition_not_a_requirement() -> None:
    prompt = _judge_prompt(
        LiveCase(id="case", title="题目", premise="前提"),
        {},
        {"must_happen": ["发生事件"], "must_not_happen": ["禁止事件"]},
        "正文 A",
        "正文 B",
    )

    assert "must_not_happen 被写出才是失败" in prompt
    assert "绝不能判为失败" in prompt
    assert "排列顺序是随机的" in prompt
    assert "平均分差小于 0.5 必须返回 TIE" in prompt
