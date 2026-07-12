"""Canonical SQLite repository and artifact storage for NovelForge."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Iterator
from uuid import UUID

from novelforge.core.models import AutoRevisionReport, Story


_REPOSITORY_LOCKS: dict[Path, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    """Return one process-local lock per canonical database path."""
    resolved = path.resolve()
    with _LOCK_GUARD:
        return _REPOSITORY_LOCKS.setdefault(resolved, threading.RLock())


@dataclass(frozen=True)
class StoryRecord:
    """Story metadata for listing without loading the full canonical state."""

    id: str
    title: str
    premise: str
    status: str
    current_chapter: int
    updated_at: str
    path: str


class StoryRepository:
    """SQLite is the only source of truth; files are read-only legacy imports or artifacts.

    The complete Pydantic Story payload remains a single transactional document for now. This
    deliberately preserves the existing domain API while establishing an unambiguous ownership
    boundary. Chroma, graph, and FTS stores are derived indexes and must never be used to recover
    canonical story state.
    """

    def __init__(
        self,
        database_path: str | Path = "./novelforge/storage/novelforge.db",
        artifact_directory: str | Path | None = None,
        legacy_state_directory: str | Path | None = None,
    ) -> None:
        raw_path = Path(database_path)
        # Backward compatibility: a directory argument means "store novelforge.db inside it".
        self.database_path = raw_path / "novelforge.db" if raw_path.suffix == "" else raw_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_directory = Path(artifact_directory or self.database_path.parent / "artifacts")
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        self.legacy_state_directory = (
            Path(legacy_state_directory)
            if legacy_state_directory is not None
            else self.database_path.parent / "story_state"
        )
        self._lock = _lock_for(self.database_path)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._migrate_legacy_records()

    def _init_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    premise TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_chapter INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS storage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_stories_updated_at ON stories(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_storage_events_pending ON storage_events(processed_at, id);
                """
            )

    def _migrate_legacy_records(self) -> None:
        """Import legacy JSON files exactly once without treating them as an active write target."""
        if self.legacy_state_directory is None or not self.legacy_state_directory.exists():
            return
        for path in self.legacy_state_directory.glob("*.json"):
            try:
                story = Story.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            with self._lock:
                exists = self._connection.execute(
                    "SELECT 1 FROM stories WHERE id = ?", (str(story.id),)
                ).fetchone()
            if exists is None:
                self.save(story, event_type="legacy_json_imported")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide the only canonical write transaction boundary."""
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def save(self, story: Story, event_type: str = "story_saved") -> Path:
        """Atomically persist a complete canonical story document and append an outbox event."""
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO stories(id, title, premise, status, current_chapter, updated_at, state_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    premise=excluded.premise,
                    status=excluded.status,
                    current_chapter=excluded.current_chapter,
                    updated_at=excluded.updated_at,
                    state_json=excluded.state_json,
                    schema_version=1
                """,
                (
                    str(story.id),
                    story.title,
                    story.premise,
                    story.status,
                    story.current_chapter,
                    story.updated_at.isoformat(),
                    story.model_dump_json(),
                ),
            )
            connection.execute(
                "INSERT INTO storage_events(story_id, event_type, created_at) VALUES (?, ?, ?)",
                (str(story.id), event_type, datetime.now(timezone.utc).isoformat()),
            )
        return self.database_path

    def load(self, story_id: str | UUID) -> Story:
        """Load canonical state, importing a legacy JSON record once when necessary."""
        normalized = str(story_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM stories WHERE id = ?", (normalized,)
            ).fetchone()
        if row is not None:
            return Story.model_validate_json(row["state_json"])
        legacy = self._legacy_path(story_id)
        if legacy is not None and legacy.exists():
            story = Story.model_validate_json(legacy.read_text(encoding="utf-8"))
            self.save(story, event_type="legacy_json_imported")
            return story
        raise FileNotFoundError(f"Story {normalized} is not stored in {self.database_path}")

    def exists(self, story_id: str | UUID) -> bool:
        normalized = str(story_id)
        with self._lock:
            row = self._connection.execute("SELECT 1 FROM stories WHERE id = ?", (normalized,)).fetchone()
        return row is not None or bool((legacy := self._legacy_path(story_id)) and legacy.exists())

    def delete(self, story_id: str | UUID) -> bool:
        """Delete only canonical state; derived indexes are deleted by the application service."""
        normalized = str(story_id)
        with self.transaction() as connection:
            cursor = connection.execute("DELETE FROM stories WHERE id = ?", (normalized,))
        artifact_root = self.artifact_directory / "stories" / normalized
        if artifact_root.exists():
            for path in sorted(artifact_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            artifact_root.rmdir()
        return cursor.rowcount > 0

    def story_path(self, story_id: str | UUID) -> Path:
        """Compatibility path: all canonical stories reside in this one database."""
        return self.database_path

    def list_records(self) -> list[StoryRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, title, premise, status, current_chapter, updated_at FROM stories ORDER BY updated_at DESC"
            ).fetchall()
        return [
            StoryRecord(
                id=row["id"],
                title=row["title"],
                premise=row["premise"],
                status=row["status"],
                current_chapter=int(row["current_chapter"]),
                updated_at=row["updated_at"],
                path=f"{self.database_path}#story={row['id']}",
            )
            for row in rows
        ]

    def pending_index_events(self, limit: int = 100) -> list[dict[str, str | int]]:
        """Expose unsynchronized canonical changes to an index worker or rebuild command."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, story_id, event_type, created_at FROM storage_events "
                "WHERE processed_at IS NULL ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def storage_status(self, story_id: str | UUID) -> dict[str, str | int]:
        """Describe ownership and pending derived-index work for one canonical story."""
        normalized = str(story_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM storage_events WHERE story_id = ? AND processed_at IS NULL",
                (normalized,),
            ).fetchone()
        return {
            "canonical_store": str(self.database_path),
            "artifact_directory": str(self.artifact_directory / "stories" / normalized),
            "pending_index_events": int(row["count"] if row else 0),
        }

    def mark_index_events_processed(self, event_ids: list[int]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE storage_events SET processed_at = ? WHERE id IN ({placeholders})",
                (datetime.now(timezone.utc).isoformat(), *event_ids),
            )

    def artifact_path(self, story_id: str | UUID, category: str, filename: str) -> Path:
        path = self.artifact_directory / "stories" / str(story_id) / category / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def export_auto_revision_report(
        self,
        story: Story,
        report: AutoRevisionReport,
        output_path: str | Path | None = None,
    ) -> Path:
        output = Path(output_path) if output_path else self.artifact_path(
            story.id, "reports", f"chapter-{report.chapter_index}-auto-revision.md"
        )
        output.write_text(self.format_auto_revision_report(story, report), encoding="utf-8")
        return output

    def format_auto_revision_report(self, story: Story, report: AutoRevisionReport) -> str:
        status = "PASSED" if report.passed else "STOPPED" if report.stopped else "NOT PASSED"
        lines = [
            f"# Auto-Revision Report: {story.title}", "",
            f"- Story ID: `{story.id}`", f"- Chapter: `{report.chapter_index}`",
            f"- Status: **{status}**", f"- Final Score: **{report.final_score:.2f}**", "", "## Rounds", "",
        ]
        if not report.rounds:
            lines.append("No rounds recorded.")
        for round_report in report.rounds:
            scores = round_report.review_report.scores
            lines.extend([
                f"### Round {round_report.round}", "", f"- Total: `{round_report.total_score:.2f}`",
                f"- Logic: `{scores.logic_consistency:.1f}`", f"- Character: `{scores.character_fidelity:.1f}`",
                f"- Foreshadowing: `{scores.foreshadowing_handling:.1f}`", f"- Pacing: `{scores.pacing:.1f}`",
                f"- Style: `{scores.style_uniformity:.1f}`", f"- Fix Summary: {round_report.modification_summary or 'N/A'}", "",
            ])
            if round_report.review_report.issues:
                lines.append("Issues:")
                lines.extend(f"- `{issue.severity}` {issue.dimension}: {issue.description}" for issue in round_report.review_report.issues)
                lines.append("")
        lines.extend(["## Residual Issues", ""])
        if report.residual_issues:
            lines.extend(f"- `{issue.severity}` {issue.dimension}: {issue.description}" for issue in report.residual_issues)
        else:
            lines.append("No residual issues recorded.")
        lines.extend(["", "## Final Content Preview", "", report.final_content[:2000]])
        return "\n".join(lines)

    def _legacy_path(self, story_id: str | UUID) -> Path | None:
        if self.legacy_state_directory is None:
            return None
        return self.legacy_state_directory / f"{story_id}.json"
