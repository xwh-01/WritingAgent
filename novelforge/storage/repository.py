"""Repository utilities for saved stories and generated artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from novelforge.core.models import AutoRevisionReport, Story


@dataclass(frozen=True)
class StoryRecord:
    """故事元数据摘要，用于列表展示，不含完整故事数据。"""

    id: str
    title: str
    premise: str
    status: str
    current_chapter: int
    updated_at: str
    path: str


class StoryRepository:
    """故事持久化仓库，负责 JSON 文件的读写、列表和删除操作。"""

    def __init__(self, state_dir: str | Path = "./novelforge/storage/story_state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, story: Story) -> Path:
        """将故事对象序列化为 JSON 文件保存到磁盘（原子写入）。"""
        path = self.story_path(story.id)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(path)  # Atomic on POSIX; best-effort on Windows
        return path

    def load(self, story_id: str | UUID) -> Story:
        """从磁盘 JSON 文件反序列化并加载故事对象。"""
        path = self.story_path(story_id)
        return Story.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, story_id: str | UUID) -> bool:
        """检查指定故事 ID 的 JSON 文件是否存在。"""
        return self.story_path(story_id).exists()

    def delete(self, story_id: str | UUID) -> bool:
        """删除指定故事的 JSON 文件，返回是否成功。"""
        path = self.story_path(story_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def story_path(self, story_id: str | UUID) -> Path:
        """根据故事 ID 构造对应的 JSON 文件路径。"""
        return self.state_dir / f"{story_id}.json"

    def list_records(self) -> list[StoryRecord]:
        """列出状态目录中所有故事文件的元数据，按修改时间降序排列。"""
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
        """将自动修订报告格式化为 Markdown 并写入文件，返回输出路径。"""
        output = Path(output_path) if output_path else self.state_dir / f"{story.id}-chapter-{report.chapter_index}-auto-report.md"
        output.write_text(self.format_auto_revision_report(story, report), encoding="utf-8")
        return output

    def format_auto_revision_report(self, story: Story, report: AutoRevisionReport) -> str:
        """将自动修订报告对象渲染为可读的 Markdown 字符串。"""
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
            if round_report.review_report.contract_checks:
                lines.append("Contract Checks:")
                for check in round_report.review_report.contract_checks:
                    confidence = f" confidence={check.confidence:.0%}" if check.validation_method == "rule+llm" else ""
                    location = f" {check.paragraph_range}" if check.paragraph_range else ""
                    lines.append(
                        f"- **{check.status}** `{check.constraint_type}`: {check.requirement}"
                        f"{confidence}{location}"
                    )
                    if check.evidence:
                        lines.append(f"  - Evidence: {check.evidence[:300]}")
                    if check.message:
                        lines.append(f"  - Note: {check.message}")
                lines.append("")
        lines.extend(["## Residual Issues", ""])
        if report.residual_issues:
            for issue in report.residual_issues:
                lines.append(f"- `{issue.severity}` {issue.dimension}: {issue.description}")
        else:
            lines.append("No residual issues recorded.")
        lines.extend(["", "## Final Content Preview", "", report.final_content[:2000]])
        return "\n".join(lines)
