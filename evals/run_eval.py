"""Run reproducible NovelForge long-form consistency evaluations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from novelforge.core.models import (
    CausalEvent,
    Character,
    CharacterState,
    ChapterOutline,
    Foreshadowing,
    Story,
)
from novelforge.longform.causality import CausalityTracker
from novelforge.longform.manager import LongformManager


CASES_DIR = Path(__file__).parent / "cases"
REPORT_PATH = Path(__file__).parent / "report.md"
JSON_REPORT_PATH = Path(__file__).parent / "report.json"
BASELINES = ("full", "without_longform_context", "without_auto_revision")


@dataclass
class EvalResult:
    case_id: str
    name: str
    category: str
    passed: bool
    matched_keywords: list[str]
    missing_keywords: list[str]
    false_positive_count: int
    issue_count: int
    baseline: str
    summary: str
    expected_keywords: list[str]
    findings: list[str]


def run_all(
    cases_dir: Path = CASES_DIR,
    report_path: Path = REPORT_PATH,
    json_report_path: Path | None = None,
    baselines: tuple[str, ...] = BASELINES,
) -> list[EvalResult]:
    results = [
        run_case(path, baseline)
        for path in sorted(cases_dir.glob("*.json"))
        for baseline in baselines
    ]
    report_path.write_text(render_report(results), encoding="utf-8")
    json_path = json_report_path or report_path.with_suffix(".json")
    json_path.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def run_case(path: Path, baseline: str = "full") -> EvalResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    story = build_story(data)
    category = normalize_category(data["category"])
    findings = collect_findings(data, story, category)
    expected_keywords = data["expected"].get("keywords", [])
    matched_keywords = [keyword for keyword in expected_keywords if keyword in "\n".join(findings)]
    missing_keywords = [keyword for keyword in expected_keywords if keyword not in matched_keywords]
    false_positive_count = sum(
        1 for finding in findings if expected_keywords and not any(keyword in finding for keyword in expected_keywords)
    )
    passed = bool(findings) and not missing_keywords
    baseline_note = baseline
    if baseline != "full":
        baseline_note += " (simulated: deterministic checkers remain active; this labels regression slices)"
    summary = (
        f"{len(findings)} issue(s), matched {len(matched_keywords)}/{len(expected_keywords)} keywords "
        f"under {baseline_note}."
    )
    return EvalResult(
        case_id=data["id"],
        name=data["name"],
        category=category,
        passed=passed,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        false_positive_count=false_positive_count,
        issue_count=len(findings),
        baseline=baseline,
        summary=summary,
        expected_keywords=expected_keywords,
        findings=findings,
    )


def collect_findings(data: dict[str, Any], story: Story, category: str) -> list[str]:
    if category == "causal_ordering":
        tracker = CausalityTracker()
        new_event = CausalEvent.model_validate(data["new_event"])
        return tracker.check_conflicts(story, new_event)
    if category == "pacing_trend":
        manager = LongformManager()
        history = []
        for item in data.get("pacing_history", []):
            analysis = manager.pacing_analyzer.analyze_chapter(item["content"])
            history.append({"chapter": item["chapter"], **analysis})
        warning = manager.pacing_analyzer.check_pacing_trend(history)
        return [] if "正常" in warning or "姝ｅ父" in warning else [warning]

    manager = LongformManager()
    chapter = data.get("chapter_under_review", {})
    findings_map = manager.review_chapter_consistency(
        story,
        chapter.get("chapter_index", story.current_chapter or 1),
        chapter.get("content", ""),
    )
    issue_type = data["expected"].get("issue_type")
    if issue_type:
        return findings_map.get(issue_type, [])
    if category == "character_consistency":
        return findings_map.get("character_state_issues", [])
    if category == "foreshadowing_lifecycle":
        return findings_map.get("foreshadowing_issues", [])
    if category == "state_transition":
        return findings_map.get("character_state_issues", [])
    return [item for values in findings_map.values() for item in values]


def normalize_category(category: str) -> str:
    return {
        "causality": "causal_ordering",
        "pacing": "pacing_trend",
        "character_state": "character_consistency",
        "foreshadowing": "foreshadowing_lifecycle",
    }.get(category, category)


def build_story(data: dict[str, Any]) -> Story:
    story_data = data.get("story", {})
    story = Story(
        title=story_data.get("title", data["id"]),
        premise=story_data.get("premise", ""),
        genre=story_data.get("genre", "novel"),
    )
    for item in data.get("characters", []):
        character = Character.model_validate({
            "id": item.get("id"),
            "name": item.get("name", item.get("id")),
            "personality": item.get("personality", ""),
        })
        story.content.characters[character.id] = character
    story.content.outlines = [ChapterOutline.model_validate(item) for item in data.get("outlines", [])]
    story.memory.foreshadowings = [Foreshadowing.model_validate(item) for item in data.get("foreshadowings", [])]
    story.memory.causal_events = [CausalEvent.model_validate(item) for item in data.get("causal_events", [])]
    story.memory.states = {
        character_id: [CharacterState.model_validate(state) for state in states]
        for character_id, states in data.get("character_states", {}).items()
    }
    chapter = data.get("chapter_under_review", {})
    story.current_chapter = chapter.get("chapter_index", 0)
    return story


def render_report(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    hit_rate = passed / total * 100 if total else 0.0
    lines = [
        "# NovelForge Evaluation Report",
        "",
        f"- Cases: `{total}`",
        f"- Passed: `{passed}`",
        f"- Hit Rate: `{hit_rate:.1f}%`",
        "- Baselines: `full`, `without_longform_context`, `without_auto_revision`",
        "- Baseline note: non-full modes are deterministic regression slices, not disabled production modules.",
        "",
        "| Case | Category | Baseline | Result | Matched | Missing | False Positives | Issues | Summary |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"| `{result.case_id}` {escape_md(result.name)} | {result.category} | {result.baseline} | "
            f"**{status}** | {escape_md(', '.join(result.matched_keywords)) or '-'} | "
            f"{escape_md(', '.join(result.missing_keywords)) or '-'} | {result.false_positive_count} | "
            f"{result.issue_count} | {escape_md(result.summary)} |"
        )
    return "\n".join(lines) + "\n"


def escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NovelForge long-form consistency evals.")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--json-report", type=Path, default=JSON_REPORT_PATH)
    parser.add_argument(
        "--baseline",
        choices=BASELINES,
        action="append",
        help="Run only selected baseline(s). Defaults to all baselines.",
    )
    args = parser.parse_args()
    baselines = tuple(args.baseline) if args.baseline else BASELINES
    results = run_all(args.cases_dir, args.report, args.json_report, baselines=baselines)
    passed = sum(1 for result in results if result.passed)
    print(f"NovelForge evals: {passed}/{len(results)} passed")
    print(f"Markdown report written to {args.report}")
    print(f"JSON report written to {args.json_report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
