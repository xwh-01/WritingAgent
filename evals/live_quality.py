"""Real-provider A/B evaluation for NovelForge prose generation.

This suite intentionally stays separate from ``evals.run_eval``. The latter is a
fast deterministic regression suite; this module produces real prose, keeps the
evidence, and refuses to claim success from an undersized or order-biased sample.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from evals.live_fixtures import fixed_case_plan
from novelforge.core.config import AppConfig, load_config
from novelforge.core.utils import extract_json
from novelforge.domain import Character
from novelforge.llm.base import LLMClient, LLMResponse
from novelforge.orchestrator.engine import NovelForgeEngine

CASES_DIR = Path(__file__).parent / "live_cases"
RESULTS_DIR = Path(__file__).parent / "live_results"


class LiveCase(BaseModel):
    id: str
    title: str
    premise: str
    genre: str = "novel"
    style_guide: str = ""
    characters: list[Character] = Field(default_factory=list)
    target_characters: int = Field(default=900, ge=300)
    rubric: list[str] = Field(default_factory=list)


class CandidateScore(BaseModel):
    plot_progression: float = Field(ge=0, le=10)
    character_fidelity: float = Field(ge=0, le=10)
    continuity: float = Field(ge=0, le=10)
    scene_quality: float = Field(ge=0, le=10)
    prose_quality: float = Field(ge=0, le=10)

    @property
    def total(self) -> float:
        return round(
            (
                self.plot_progression
                + self.character_fidelity
                + self.continuity
                + self.scene_quality
                + self.prose_quality
            )
            / 5,
            2,
        )


class JudgeDecision(BaseModel):
    winner: Literal["A", "B", "TIE"]
    scores: dict[str, CandidateScore]
    hard_failures: dict[str, list[str]] = Field(default_factory=dict)
    reason: str


@dataclass(frozen=True)
class PairDecision:
    first: str
    second: str
    resolved_winner: str
    consistent: bool
    consistency_mode: str = "exact"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _response_dict(response: LLMResponse) -> dict[str, Any]:
    data = asdict(response)
    data.pop("content", None)
    return data


def _call_metrics(responses: list[LLMResponse]) -> dict[str, int | None]:
    """Aggregate provider evidence without estimating unavailable token usage."""
    def total(field: str) -> int | None:
        values = [getattr(item, field) for item in responses]
        known = [int(value) for value in values if value is not None]
        return sum(known) if known else None

    return {
        "calls": len(responses),
        "prompt_tokens": total("prompt_tokens"),
        "completion_tokens": total("completion_tokens"),
        "total_tokens": total("total_tokens"),
        "latency_ms": total("latency_ms"),
    }


def _history_since(llm: LLMClient, start: int) -> list[LLMResponse]:
    history = getattr(llm, "call_history", None)
    return list(history[start:]) if isinstance(history, list) else []


def _judge_failures(
    first: JudgeDecision,
    second: JudgeDecision,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Require swapped-order corroboration before calling a hard failure.

    A one-sided claim is retained as an audit dispute, but not promoted to a
    binary failure: the same blind judge saw the candidate under the other
    presentation order and did not reproduce it.  This prevents an isolated
    label/position hallucination from defeating a cited contract check.
    """
    baseline_first = list(first.hard_failures.get("A", []))
    baseline_second = list(second.hard_failures.get("B", []))
    treatment_first = list(first.hard_failures.get("B", []))
    treatment_second = list(second.hard_failures.get("A", []))

    def corroborated(left: list[str], right: list[str]) -> tuple[list[str], list[str]]:
        if left and right:
            return list(dict.fromkeys([*left, *right])), []
        return [], list(dict.fromkeys([*left, *right]))

    baseline, baseline_disputed = corroborated(baseline_first, baseline_second)
    treatment, treatment_disputed = corroborated(treatment_first, treatment_second)
    return baseline, treatment, baseline_disputed, treatment_disputed


def _live_config(base: AppConfig, root: Path, target_characters: int) -> AppConfig:
    data = base.model_dump()
    data["indexes"]["vector_store"] = "in_memory"
    data["storage"] = {
        "database_path": str(root / "novelforge.db"),
        "artifact_directory": str(root / "artifacts"),
        "vector_index_directory": str(root / "vector"),
        "graph_index_directory": str(root / "graph"),
        "full_text_index_path": str(root / "fts.sqlite3"),
    }
    data["story"]["default_chapters"] = 1
    data["story"]["prose_target_words"] = target_characters
    data["story"]["auto_polish_drafts"] = False
    return AppConfig.model_validate(data)


def _baseline_prompt(case: LiveCase, outline: dict[str, Any], contract: dict[str, Any]) -> str:
    return (
        "请根据给定条件直接写小说第一章正文。不要解释创作思路，不要输出提纲或 Markdown。\n"
        f"目标约 {case.target_characters} 个中文字符。\n"
        f"故事前提：{case.premise}\n"
        f"文风：{case.style_guide}\n"
        f"人物：{json.dumps([item.model_dump() for item in case.characters], ensure_ascii=False)}\n"
        f"章节大纲：{json.dumps(outline, ensure_ascii=False)}\n"
        f"章节约束：{json.dumps(contract, ensure_ascii=False)}"
    )


def _judge_prompt(
    case: LiveCase,
    outline: dict[str, Any],
    contract: dict[str, Any],
    candidate_a: str,
    candidate_b: str,
) -> str:
    rubric = case.rubric or [
        "章节目标和冲突是否在场景中真正发生，而不是只被概述",
        "人物选择是否符合设定且产生可见代价",
        "信息、位置、物品和人物知识边界是否自洽",
        "场景是否有目标、阻碍、转折和不可逆状态变化",
        "语言是否具体、克制、自然，少套话和空泛心理总结",
    ]
    return (
        "你是独立小说评审。A/B 的来源已隐藏，不得猜测生成方式。"
        "章节约束是唯一的硬约束来源：必须逐条以其 must_happen 和 must_not_happen 为准。"
        "must_happen 未发生才是失败；must_not_happen 被写出才是失败，未写出禁止事项绝不能判为失败。"
        "判定 must_not_happen 失败必须引用正文中已经完成的禁止行动或结果。除非禁项明确禁止，"
        "不得把意图、犹豫、准备、未启用的工具、命令、威胁、拒绝或未来可能性当作已发生的行动；"
        "若 ending_hook 明确要求‘尚未启用’工具或‘尚未行动’，那正是该禁项没有发生的证据。"
        "若禁项要求尚未作出‘最终决定/明确选择’，列举仍在权衡的选项、停住的手或未按下的按钮"
        "不是选择；只有文本明确选定并承诺某一行动或结果才是失败。不得把角色提出方案、服从命令"
        "或尚未实行的思考升级为擅自行动，除非禁项明确禁止这些行为。"
        "不得把前提、评分细则或自己的叙事偏好升级为与章节约束矛盾的硬失败。"
        "先检查硬约束，再分别依据每篇自己的文本证据独立评分。候选 A/B 的排列顺序是随机的，"
        "绝不能给先出现者、A 标签或更长篇幅默认加分。先在内部计算两份平均分，再选择赢家；"
        "平均分差小于 0.5 必须返回 TIE，winner 必须与输出分数一致。"
        "严格输出 JSON，格式为："
        '{"winner":"A|B|TIE","scores":{"A":{"plot_progression":0-10,'
        '"character_fidelity":0-10,"continuity":0-10,"scene_quality":0-10,'
        '"prose_quality":0-10},"B":{同样字段}},'
        '"hard_failures":{"A":[],"B":[]},"reason":"简洁且引用具体文本证据"}。\n'
        f"故事前提：{case.premise}\n"
        f"章节大纲：{json.dumps(outline, ensure_ascii=False)}\n"
        f"章节约束：{json.dumps(contract, ensure_ascii=False)}\n"
        f"评分细则：{json.dumps(rubric, ensure_ascii=False)}\n\n"
        f"候选 A：\n{candidate_a}\n\n候选 B：\n{candidate_b}"
    )


def _judge(
    llm: LLMClient,
    case: LiveCase,
    outline: dict[str, Any],
    contract: dict[str, Any],
    candidate_a: str,
    candidate_b: str,
) -> tuple[JudgeDecision, list[LLMResponse]]:
    prompt = _judge_prompt(case, outline, contract, candidate_a, candidate_b)
    response = llm.chat_completion_result(
        [
            {
                "role": "system",
                "content": "只做无位置偏好的盲评并输出合法 JSON；赢家必须由两篇各自的分项总分导出。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    try:
        return JudgeDecision.model_validate(extract_json(response.content)), [response]
    except Exception as exc:
        repair = llm.chat_completion_result(
            [
                {
                    "role": "system",
                    "content": "你是严格的 JSON 修复器。只输出合法 JSON，不要解释。",
                },
                {
                    "role": "user",
                    "content": (
                        "将以下盲评结果修复为符合 JSON Schema 的对象。保留原有的赢家、分数、"
                        "硬约束失败项和理由；不得重新评判候选文本或添加新事实。\n"
                        f"解析错误：{exc}\n"
                        f"JSON Schema：{json.dumps(JudgeDecision.model_json_schema(), ensure_ascii=False)}\n"
                        f"待修复结果：{response.content}"
                    ),
                },
            ],
            temperature=0.0,
        )
        return JudgeDecision.model_validate(extract_json(repair.content)), [response, repair]


def resolve_pair(first: JudgeDecision, second: JudgeDecision) -> PairDecision:
    """Map the swapped second decision back to treatment/baseline labels."""

    def map_winner(winner: str, treatment_label: str) -> str:
        if winner == "TIE":
            return "tie"
        return "treatment" if winner == treatment_label else "baseline"

    first_winner = map_winner(first.winner, "B")
    second_winner = map_winner(second.winner, "A")
    if first_winner == second_winner:
        return PairDecision(
            first=first_winner,
            second=second_winner,
            resolved_winner=first_winner,
            consistent=True,
            consistency_mode="exact",
        )
    # A tie is an interval (difference below the declared scoring margin), not
    # the opposite of a small directional preference.  Treat tie+treatment and
    # tie+baseline as order-compatible but conservatively resolve them to tie.
    # Only treatment-vs-baseline is a true presentation-order reversal.
    if {first_winner, second_winner} in ({"tie", "treatment"}, {"tie", "baseline"}):
        return PairDecision(
            first=first_winner,
            second=second_winner,
            resolved_winner="tie",
            consistent=True,
            consistency_mode="tie_tolerant",
        )
    return PairDecision(
        first=first_winner,
        second=second_winner,
        resolved_winner="uncertain",
        consistent=False,
        consistency_mode="reversal",
    )


def _hard_metrics(text: str, case: LiveCase) -> dict[str, Any]:
    stripped = text.strip()
    forbidden = ["创作思路", "以下是", "```", "作为一个AI"]
    return {
        "characters": len(stripped),
        "non_empty": bool(stripped),
        "character_names_present": {
            item.name: item.name in stripped for item in case.characters
        },
        "forbidden_markers": [marker for marker in forbidden if marker in stripped],
        "content_sha256": _sha256(stripped),
    }


def run_trial(case: LiveCase, config: AppConfig, trial_index: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"novelforge-live-{case.id}-") as temp:
        engine = NovelForgeEngine(_live_config(config, Path(temp), case.target_characters))
        try:
            engine.start_new_story(
                premise=case.premise,
                title=case.title,
                genre=case.genre,
                style_guide=case.style_guide,
            )
            for character in case.characters:
                engine.upsert_character(character)
            fixture = fixed_case_plan(case.id)
            if fixture is None:
                outline = engine.generate_outline(1)[0]
                contract = engine.ensure_chapter_contract(1)
                contract_source = "generated"
            else:
                outline, contract = fixture
                # The generation path consumes the explicit values below, but
                # keeping them on the story also grounds context and reviewer
                # snapshots without spending planner calls that would mutate
                # the benchmark contract.
                engine.current_story.design.outlines = [outline]
                engine.current_story.design.chapter_contracts = {outline.chapter_index: contract}
                contract_source = "frozen_fixture"
            outline_data = outline.model_dump()
            contract_data = contract.model_dump()

            baseline_prompt = _baseline_prompt(case, outline_data, contract_data)
            baseline_start = len(getattr(engine.llm, "call_history", []))
            baseline_response = engine.llm.chat_completion_result(
                [
                    {"role": "system", "content": "你是长篇小说作者。"},
                    {"role": "user", "content": baseline_prompt},
                ],
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
            )
            baseline_calls = _history_since(engine.llm, baseline_start) or [baseline_response]
            treatment_start = len(getattr(engine.llm, "call_history", []))
            treatment = engine.generation.generate(
                engine.current_story,
                outline,
                contract,
                engine._polish_draft,
            )
            treatment_calls = _history_since(engine.llm, treatment_start)
            treatment_text = treatment.candidate.content

            first, first_meta = _judge(
                engine.llm,
                case,
                outline_data,
                contract_data,
                baseline_response.content,
                treatment_text,
            )
            second, second_meta = _judge(
                engine.llm,
                case,
                outline_data,
                contract_data,
                treatment_text,
                baseline_response.content,
            )
            pair = resolve_pair(first, second)
            (
                baseline_failures,
                treatment_failures,
                baseline_disputed_failures,
                treatment_disputed_failures,
            ) = _judge_failures(first, second)
            history = getattr(engine.llm, "call_history", [])
            return {
                "trial": trial_index,
                "case_id": case.id,
                "contract_source": contract_source,
                "outline": outline_data,
                "contract": contract_data,
                "baseline": {
                    "content": baseline_response.content,
                    "metrics": _hard_metrics(baseline_response.content, case),
                    "call": _response_dict(baseline_response),
                    "call_metrics": _call_metrics(baseline_calls),
                    "judge_hard_failures": baseline_failures,
                    "judge_disputed_hard_failures": baseline_disputed_failures,
                    "judge_hard_constraints_passed": not baseline_failures,
                    "prompt_sha256": _sha256(baseline_prompt),
                },
                "treatment": {
                    "content": treatment_text,
                    "metrics": _hard_metrics(treatment_text, case),
                    "accepted_by_internal_gate": treatment.accepted,
                    "final_score": treatment.final_assessment.score,
                    "budget": treatment.budget.model_dump(mode="json") if treatment.budget else None,
                    "candidate_selections": [
                        item.model_dump(mode="json") for item in treatment.candidate_selections
                    ],
                    "call_metrics": _call_metrics(treatment_calls),
                    "judge_hard_failures": treatment_failures,
                    "judge_disputed_hard_failures": treatment_disputed_failures,
                    "judge_hard_constraints_passed": not treatment_failures,
                    "all_hard_constraints_passed": treatment.accepted and not treatment_failures,
                    "attempts": [
                        {
                            "attempt": item.attempt,
                            "score": item.score,
                            "decision": str(item.decision),
                            "reasons": list(item.reasons),
                            "review_mode": item.review_mode,
                            "repair_obligation_ids": list(item.repair_obligation_ids),
                            "changed_scene_indexes": list(item.changed_scene_indexes),
                            "contract_checks": [
                                check.model_dump(mode="json") for check in item.contract_checks
                            ],
                            "failure_categories": sorted(
                                {
                                    entry.failure_category
                                    for entry in (item.evidence_ledger.entries if item.evidence_ledger else [])
                                    if entry.failure_category
                                }
                            ),
                            "evidence_ledger": (
                                item.evidence_ledger.model_dump(mode="json")
                                if item.evidence_ledger
                                else None
                            ),
                        }
                        for item in treatment.assessments
                    ],
                },
                "blind_judges": [
                    {
                        "order": "baseline,treatment",
                        "decision": first.model_dump(),
                        "calls": [_response_dict(item) for item in first_meta],
                    },
                    {
                        "order": "treatment,baseline",
                        "decision": second.model_dump(),
                        "calls": [_response_dict(item) for item in second_meta],
                    },
                ],
                "pair_decision": asdict(pair),
                "provider_calls": [_response_dict(item) for item in history],
            }
        finally:
            engine.close()


def summarize(trials: list[dict[str, Any]], minimum_trials: int = 3) -> dict[str, Any]:
    completed = [item for item in trials if "pair_decision" in item]
    failed = [item for item in trials if "pair_decision" not in item]
    decisions = [item["pair_decision"]["resolved_winner"] for item in completed]
    consistent = sum(bool(item["pair_decision"]["consistent"]) for item in completed)
    treatment_wins = decisions.count("treatment")
    baseline_wins = decisions.count("baseline")
    ties = decisions.count("tie")
    uncertain = decisions.count("uncertain")
    resolved = treatment_wins + baseline_wins + ties
    conclusive = len(completed) >= minimum_trials and uncertain / len(completed) <= 0.2
    # Only swapped-order-consistent decisions are quality evidence. A failed
    # call or an order-sensitive decision must not silently become a 0% win.
    win_rate = treatment_wins / resolved if resolved else None
    if not conclusive:
        verdict = "insufficient_evidence"
    elif win_rate >= 0.6 and treatment_wins > baseline_wins:
        verdict = "treatment_better"
    elif baseline_wins > treatment_wins:
        verdict = "treatment_worse"
    else:
        verdict = "no_clear_improvement"
    def rate(values: list[bool]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    def metric_average(side: str, field: str) -> float | None:
        values = [
            item.get(side, {}).get("call_metrics", {}).get(field)
            for item in completed
            if item.get(side, {}).get("call_metrics", {}).get(field) is not None
        ]
        return round(sum(values) / len(values), 2) if values else None

    baseline_metrics = {
        field: metric_average("baseline", field)
        for field in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms")
    }
    treatment_metrics = {
        field: metric_average("treatment", field)
        for field in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms")
    }
    change = {
        field: (
            None
            if baseline_metrics[field] is None or treatment_metrics[field] is None
            else round(treatment_metrics[field] - baseline_metrics[field], 2)
        )
        for field in baseline_metrics
    }
    review_mode_counts: dict[str, int] = {}
    failure_categories: dict[str, int] = {}
    selected_scene_count = 0
    trials_with_selection = 0
    budget_exhausted_trials = 0
    for item in completed:
        treatment = item.get("treatment", {})
        selections = treatment.get("candidate_selections", [])
        if selections:
            trials_with_selection += 1
            selected_scene_count += len(selections)
        if (treatment.get("budget") or {}).get("exhausted_reason"):
            budget_exhausted_trials += 1
        for attempt in treatment.get("attempts", []):
            mode = str(attempt.get("review_mode") or "unknown")
            review_mode_counts[mode] = review_mode_counts.get(mode, 0) + 1
            for category in attempt.get("failure_categories", []):
                failure_categories[category] = failure_categories.get(category, 0) + 1
    return {
        "trials": len(completed),
        "attempted_trials": len(trials),
        "failed_trials": len(failed),
        "execution_failures": [
            {
                "case_id": item.get("case_id", "unknown"),
                "trial": item.get("trial"),
                "error_type": item.get("error_type", "unknown_error"),
                "error": item.get("error", ""),
            }
            for item in failed
        ],
        "minimum_trials": minimum_trials,
        "order_consistency_rate": round(consistent / len(completed), 3) if completed else None,
        "treatment_wins": treatment_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "uncertain": uncertain,
        "treatment_win_rate": round(win_rate, 3) if win_rate is not None else None,
        "hard_constraint_pass_rates": {
            "baseline_judge": rate(
                [
                    bool(item.get("baseline", {}).get("judge_hard_constraints_passed"))
                    for item in completed
                ]
            ),
            "treatment_judge": rate(
                [
                    bool(item.get("treatment", {}).get("judge_hard_constraints_passed"))
                    for item in completed
                ]
            ),
            "treatment_internal_gate": rate(
                [bool(item.get("treatment", {}).get("accepted_by_internal_gate")) for item in completed]
            ),
            "treatment_all": rate(
                [bool(item.get("treatment", {}).get("all_hard_constraints_passed")) for item in completed]
            ),
        },
        "average_generation_call_metrics": {
            "baseline": baseline_metrics,
            "treatment": treatment_metrics,
            "treatment_minus_baseline": change,
        },
        "review_mode_counts": review_mode_counts,
        "failure_categories": failure_categories,
        "quality_search": {
            "selected_scene_count": selected_scene_count,
            "trials_with_selection": trials_with_selection,
            "budget_exhausted_trials": budget_exhausted_trials,
        },
        "verdict": verdict,
    }


def recompute_saved_summary(output_dir: Path) -> Path:
    """Apply the current blind-aggregation protocol to immutable raw trials.

    Live provider output remains in ``*-N.json`` files.  This command only
    remaps the two saved blind decisions to their baseline/treatment labels,
    so a protocol improvement can be audited without paying to regenerate
    prose or overwriting the original summary.
    """
    if not output_dir.is_dir():
        raise RuntimeError(f"Missing live evaluation directory: {output_dir}")
    trials: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("*.json")):
        if path.name.startswith("summary"):
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        judges = item.get("blind_judges")
        if not isinstance(judges, list) or len(judges) != 2:
            trials.append(item)
            continue
        first = JudgeDecision.model_validate(judges[0].get("decision", {}))
        second = JudgeDecision.model_validate(judges[1].get("decision", {}))
        pair = resolve_pair(first, second)
        (
            baseline_failures,
            treatment_failures,
            baseline_disputed_failures,
            treatment_disputed_failures,
        ) = _judge_failures(first, second)
        item["pair_decision"] = asdict(pair)
        for side, failures, disputed in (
            ("baseline", baseline_failures, baseline_disputed_failures),
            ("treatment", treatment_failures, treatment_disputed_failures),
        ):
            subject = item.setdefault(side, {})
            subject["judge_hard_failures"] = failures
            subject["judge_disputed_hard_failures"] = disputed
            subject["judge_hard_constraints_passed"] = not failures
        treatment = item.setdefault("treatment", {})
        treatment["all_hard_constraints_passed"] = bool(
            treatment.get("accepted_by_internal_gate") and not treatment_failures
        )
        trials.append(item)

    original_summary_path = output_dir / "summary.json"
    original = (
        json.loads(original_summary_path.read_text(encoding="utf-8"))
        if original_summary_path.is_file()
        else {}
    )
    report = {
        **original,
        "recomputed_at": datetime.now(UTC).isoformat(),
        "aggregation_protocol": "swapped_order_v2_corroborated_hard_failures",
        "raw_trial_files": [path.name for path in sorted(output_dir.glob("*-*.json"))],
        "summary": summarize(trials),
    }
    destination = output_dir / "summary.recomputed.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def run_suite(
    cases_dir: Path = CASES_DIR,
    output_dir: Path | None = None,
    repetitions: int = 3,
    config_path: Path | None = None,
    case_ids: set[str] | None = None,
    resume: bool = False,
) -> Path:
    config = load_config(config_path)
    if config.llm.provider.lower() in {"mock", "local", "fake"}:
        raise RuntimeError("Live quality evaluation refuses mock providers.")
    cases = [
        LiveCase.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(cases_dir.glob("*.json"))
    ]
    if case_ids:
        found = {case.id for case in cases}
        unknown = case_ids - found
        if unknown:
            raise RuntimeError("Unknown live evaluation case(s): " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case.id in case_ids]
    if not cases:
        raise RuntimeError(f"No live evaluation cases found in {cases_dir}.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir or RESULTS_DIR / stamp
    if resume:
        if output_dir is None:
            raise RuntimeError("--resume requires an explicit --output-dir.")
        if not destination.is_dir():
            raise RuntimeError(f"Cannot resume missing evaluation directory: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)

    existing_trials: list[dict[str, Any]] = []
    if resume:
        for path in sorted(destination.glob("*.json")):
            if path.name == "summary.json":
                continue
            trial = json.loads(path.read_text(encoding="utf-8"))
            if trial.get("case_id") in {case.id for case in cases}:
                existing_trials.append(trial)

    trials = list(existing_trials)
    for case in cases:
        prior_indices = [
            int(item["trial"])
            for item in existing_trials
            if item.get("case_id") == case.id and isinstance(item.get("trial"), int)
        ]
        first_index = max(prior_indices, default=0) + 1
        for index in range(first_index, first_index + repetitions):
            try:
                trial = run_trial(case, config, index)
            except Exception as exc:
                trial = {
                    "trial": index,
                    "case_id": case.id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            trials.append(trial)
            (destination / f"{case.id}-{index}.json").write_text(
                json.dumps(trial, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
    report = {
        "kind": "real_provider_blind_ab",
        "created_at": datetime.now(UTC).isoformat(),
        "git_revision": _git_revision(),
        "provider": config.llm.provider,
        "model": config.llm.model,
        "temperature": config.llm.temperature,
        "cases": [case.id for case in cases],
        "summary": summarize(trials),
        "trial_files": [f"{item['case_id']}-{item['trial']}.json" for item in trials],
    }
    (destination / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-provider blind A/B prose evals.")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--recompute-dir",
        type=Path,
        help="Recompute a saved summary from raw blind-judge files without provider calls.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append repetitions to an existing --output-dir after an interrupted run.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this live case ID. Repeat to select multiple cases.",
    )
    args = parser.parse_args()
    if args.recompute_dir is not None:
        destination = recompute_saved_summary(args.recompute_dir)
        summary = json.loads(destination.read_text(encoding="utf-8"))["summary"]
        print(json.dumps(summary, ensure_ascii=False))
        print(f"Recomputed evidence written to {destination}")
        return 0
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    destination = run_suite(
        cases_dir=args.cases_dir,
        output_dir=args.output_dir,
        repetitions=args.repetitions,
        config_path=args.config,
        case_ids=set(args.case_ids) if args.case_ids else None,
        resume=args.resume,
    )
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    print(json.dumps(summary["summary"], ensure_ascii=False))
    print(f"Evidence written to {destination}")
    failed = int(summary["summary"].get("failed_trials", 0))
    return 0 if summary["summary"]["verdict"] != "treatment_worse" and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
