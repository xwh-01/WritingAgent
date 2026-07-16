"""Canonical SQLite repository for complete Story aggregates."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import UUID

from novelforge.core.exceptions import ConcurrentUpdateError
from novelforge.domain import Story

_LOCKS: dict[Path, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCK_GUARD:
        return _LOCKS.setdefault(resolved, threading.RLock())


@dataclass(frozen=True)
class StoryRecord:
    id: str
    title: str
    premise: str
    status: str
    current_chapter: int
    revision: int
    updated_at: str
    path: str


class StoryRepository:
    """Store each aggregate transactionally as one validated JSON document.

    SQLite is authoritative. Search indexes and exported files are projections
    and must never be used to reconstruct a Story.
    """

    def __init__(self, database_path: str | Path = "./.data/novelforge/novelforge.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.database_path)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript("""
                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    premise TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_chapter INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 2,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS projection_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_stories_updated
                    ON stories(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_outbox_pending
                    ON projection_outbox(processed_at, id);
                """)
            columns = {row[1] for row in self._connection.execute("PRAGMA table_info(stories)")}
            if "revision" not in columns:
                self._connection.execute(
                    "ALTER TABLE stories ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
            current_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version < 2:
                self._connection.execute("PRAGMA user_version=2")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def save(self, story: Story, event_type: str | None = None) -> Story:
        snapshot = story.model_copy(deep=True)
        snapshot.assert_consistent()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT revision FROM stories WHERE id = ?",
                (str(snapshot.id),),
            ).fetchone()
            if existing is None:
                if snapshot.revision != 0:
                    raise ConcurrentUpdateError(
                        f"New story {snapshot.id} must start at revision 0, "
                        f"got {snapshot.revision}."
                    )
                snapshot.revision = 1
                connection.execute(
                    """
                    INSERT INTO stories(
                        id, title, premise, status, current_chapter,
                        updated_at, state_json, schema_version, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 2, ?)
                    """,
                    (
                        str(snapshot.id),
                        snapshot.title,
                        snapshot.premise,
                        snapshot.status,
                        snapshot.current_chapter,
                        snapshot.updated_at.isoformat(),
                        snapshot.model_dump_json(),
                        snapshot.revision,
                    ),
                )
            else:
                current_revision = int(existing["revision"])
                if snapshot.revision != current_revision:
                    raise ConcurrentUpdateError(
                        f"Story {snapshot.id} changed from revision "
                        f"{snapshot.revision} to {current_revision}; reload before saving."
                    )
                snapshot.revision = current_revision + 1
                cursor = connection.execute(
                    """
                    UPDATE stories SET
                        title = ?, premise = ?, status = ?, current_chapter = ?,
                        updated_at = ?, state_json = ?, schema_version = 2, revision = ?
                    WHERE id = ? AND revision = ?
                    """,
                    (
                        snapshot.title,
                        snapshot.premise,
                        snapshot.status,
                        snapshot.current_chapter,
                        snapshot.updated_at.isoformat(),
                        snapshot.model_dump_json(),
                        snapshot.revision,
                        str(snapshot.id),
                        current_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentUpdateError(f"Story {snapshot.id} was updated concurrently.")
            if event_type:
                connection.execute(
                    """
                    INSERT INTO projection_outbox(story_id, event_type, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (str(snapshot.id), event_type, datetime.now(timezone.utc).isoformat()),
                )
        return snapshot

    def load(self, story_id: str | UUID) -> Story:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json, revision FROM stories WHERE id = ?",
                (str(story_id),),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Story {story_id} is not stored in {self.database_path}.")
        story = Story.model_validate_json(row["state_json"])
        story.revision = int(row["revision"])
        return story

    def exists(self, story_id: str | UUID) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM stories WHERE id = ?",
                (str(story_id),),
            ).fetchone()
        return row is not None

    def delete(self, story_id: str | UUID) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM stories WHERE id = ?",
                (str(story_id),),
            )
        return cursor.rowcount > 0

    def list_records(self) -> list[StoryRecord]:
        with self._lock:
            rows = self._connection.execute("""
                SELECT id, title, premise, status, current_chapter, revision, updated_at
                FROM stories ORDER BY updated_at DESC
                """).fetchall()
        return [
            StoryRecord(
                id=row["id"],
                title=row["title"],
                premise=row["premise"],
                status=row["status"],
                current_chapter=int(row["current_chapter"]),
                revision=int(row["revision"]),
                updated_at=row["updated_at"],
                path=f"{self.database_path}#story={row['id']}",
            )
            for row in rows
        ]

    def pending_index_events(self, limit: int = 100) -> list[dict[str, str | int]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, story_id, event_type, created_at
                FROM projection_outbox
                WHERE processed_at IS NULL
                ORDER BY id LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_index_event_count(self, story_id: str | UUID) -> int:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS count FROM projection_outbox
                WHERE story_id = ? AND processed_at IS NULL
                """,
                (str(story_id),),
            ).fetchone()
        return int(row["count"] if row else 0)

    def pending_index_event_ids(self, story_id: str | UUID) -> list[int]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id FROM projection_outbox
                WHERE story_id = ? AND processed_at IS NULL ORDER BY id
                """,
                (str(story_id),),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def mark_index_events_processed(self, event_ids: list[int]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE projection_outbox SET processed_at = ? WHERE id IN ({placeholders})",
                (datetime.now(timezone.utc).isoformat(), *event_ids),
            )

    def close(self) -> None:
        """Release the SQLite connection owned by this repository instance."""
        with self._lock:
            self._connection.close()


__all__ = ["StoryRecord", "StoryRepository"]
