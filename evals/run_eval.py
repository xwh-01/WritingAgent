"""Run reproducible NovelForge long-form consistency evaluations."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
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


@dataclass
class EvalResult:
    case_id: str
    name: str
    category: str
    expected_keywords: list[str]
    findings: list[str]
    passed: bool


def run_all(cases_dir: Path = CASES_DIR, report_path: Path = REPORT_PATH) -> list[EvalResult]:
    results = [run_case(path) for path in sorted(cases_dir.glob("*.json"))]
    report_path.write_text(render_report(results), encoding="utf-8")
    return results


def run_case(path: Path) -> EvalResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    story = build_story(data)
    category = data["category"]
    findings: list[str]

    if category == "causality":
        tracker = CausalityTracker()
        new_event = CausalEvent.model_validate(data["new_event"])
        findings = tracker.check_conflicts(story, new_event)
    elif category == "pacing":
        manager = LongformManager()
        history = []
        for item in data.get("pacing_history", []):
            analysis = manager.pacing_analyzer.analyze_chapter(item["content"])
            history.append({"chapter": item["chapter"], **analysis})
        warning = manager.pacing_analyzer.check_pacing_trend(history)
        findings = [] if warning == "节奏趋势正常。" else [warning]
    else:
        manager = LongformManager()
        chapter = data.get("chapter_under_review", {})
        findings_map = manager.review_chapter_consistency(
            story,
            chapter.get("chapter_index", story.current_chapter or 1),
            chapter.get("content", ""),
        )
        findings = findings_map.get(data["expected"]["issue_type"], [])

    expected_keywords = data["expected"].get("keywords", [])
    passed = matches_keywords(findings, expected_keywords)
    return EvalResult(
        case_id=data["id"],
        name=data["name"],
        category=category,
        expected_keywords=expected_keywords,
        findings=findings,
        passed=passed,
    )


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
        story.characters[character.id] = character
    story.outlines = [ChapterOutline.model_validate(item) for item in data.get("outlines", [])]
    story.foreshadowings = [Foreshadowing.model_validate(item) for item in data.get("foreshadowings", [])]
    story.causal_events = [CausalEvent.model_validate(item) for item in data.get("causal_events", [])]
    story.character_states = {
        character_id: [CharacterState.model_validate(state) for state in states]
        for character_id, states in data.get("character_states", {}).items()
    }
    chapter = data.get("chapter_under_review", {})
    story.current_chapter = chapter.get("chapter_index", 0)
    return story


def matches_keywords(findings: list[str], keywords: list[str]) -> bool:
    text = "\n".join(findings)
    return bool(findings) and all(keyword in text for keyword in keywords)


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
        "",
        "| Case | Category | Result | Expected Keywords | Findings |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        keywords = ", ".join(result.expected_keywords)
        findings = "<br>".join(escape_md(item) for item in result.findings) or "No findings"
        lines.append(
            f"| `{result.case_id}` {escape_md(result.name)} | {result.category} | **{status}** | "
            f"{escape_md(keywords)} | {findings} |"
        )
    return "\n".join(lines) + "\n"


def escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NovelForge long-form consistency evals.")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    results = run_all(args.cases_dir, args.report)
    passed = sum(1 for result in results if result.passed)
    print(f"NovelForge evals: {passed}/{len(results)} passed")
    print(f"Report written to {args.report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
