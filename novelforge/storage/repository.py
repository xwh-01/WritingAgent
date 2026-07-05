"""Repository utilities for saved stories and generated artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from novelforge.core.models import AutoRevisionReport, Story


@dataclass(frozen=True)
class StoryRecord:
    id: str
    title: str
    premise: str
    status: str
    current_chapter: int
    updated_at: str
    path: str


class StoryRepository:
    def __init__(self, state_dir: str | Path = "./novelforge/storage/story_state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, story: Story) -> Path:
        path = self.story_path(story.id)
        path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, story_id: str | UUID) -> Story:
        path = self.story_path(story_id)
        return Story.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, story_id: str | UUID) -> bool:
        return self.story_path(story_id).exists()

    def story_path(self, story_id: str | UUID) -> Path:
        return self.state_dir / f"{story_id}.json"

    def list_records(self) -> list[StoryRecord]:
        records: list[StoryRecord] = []
        for path in sorted(self.state_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                story = Story.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            records.append(
                StoryRecord(
                    id=str(story.id),
                    title=story.title,
                    premise=story.premise,
                    status=story.status,
                    current_chapter=story.current_chapter,
                    updated_at=story.updated_at.isoformat(),
                    path=str(path),
                )
            )
        return records

    def export_auto_revision_report(
        self,
        story: Story,
        report: AutoRevisionReport,
        output_path: str | Path | None = None,
    ) -> Path:
        output = Path(output_path) if output_path else self.state_dir / f"{story.id}-chapter-{report.chapter_index}-auto-report.md"
        output.write_text(self.format_auto_revision_report(story, report), encoding="utf-8")
        return output

    def format_auto_revision_report(self, story: Story, report: AutoRevisionReport) -> str:
        status = "PASSED" if report.passed else "STOPPED" if report.stopped else "NOT PASSED"
        lines = [
            f"# Auto-Revision Report: {story.title}",
            "",
            f"- Story ID: `{story.id}`",
            f"- Chapter: `{report.chapter_index}`",
            f"- Status: **{status}**",
            f"- Final Score: **{report.final_score:.2f}**",
            "",
            "## Rounds",
            "",
        ]
        if not report.rounds:
            lines.append("No rounds recorded.")
        for round_report in report.rounds:
            scores = round_report.review_report.scores
            lines.extend(
                [
                    f"### Round {round_report.round}",
                    "",
                    f"- Total: `{round_report.total_score:.2f}`",
                    f"- Logic: `{scores.logic_consistency:.1f}`",
                    f"- Character: `{scores.character_fidelity:.1f}`",
                    f"- Foreshadowing: `{scores.foreshadowing_handling:.1f}`",
                    f"- Pacing: `{scores.pacing:.1f}`",
                    f"- Style: `{scores.style_uniformity:.1f}`",
                    f"- Fix Summary: {round_report.modification_summary or 'N/A'}",
                    "",
                ]
            )
            if round_report.review_report.issues:
                lines.append("Issues:")
                for issue in round_report.review_report.issues:
                    lines.append(f"- `{issue.severity}` {issue.dimension}: {issue.description}")
                lines.append("")
        lines.extend(["## Residual Issues", ""])
        if report.residual_issues:
            for issue in report.residual_issues:
                lines.append(f"- `{issue.severity}` {issue.dimension}: {issue.description}")
        else:
            lines.append("No residual issues recorded.")
        lines.extend(["", "## Final Content Preview", "", report.final_content[:2000]])
        return "\n".join(lines)
