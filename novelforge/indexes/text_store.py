"""SQLite FTS full-text index for chapters and notes."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from novelforge.indexes.interfaces import IFTSStore


class SQLiteFTSStore(IFTSStore):
    """SQLite FTS5 store with story, chapter and thread-safety boundaries."""

    def __init__(self, sqlite_path: str):
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self._fts_enabled = True
        self._init_schema()

    def index_document(self, doc_id: str, content: str) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO documents(doc_id, content) VALUES (?, ?)",
                (doc_id, content),
            )
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
                self.connection.execute(
                    "INSERT INTO documents_fts(rowid, doc_id, content) "
                    "VALUES ((SELECT rowid FROM documents WHERE doc_id = ?), ?, ?)",
                    (doc_id, doc_id, content),
                )

    def search(
        self,
        query: str,
        limit: int = 10,
        story_id: str | None = None,
        max_chapter: int | None = None,
    ) -> list[str]:
        if not query.strip():
            return []
        prefix = f"{story_id}:%" if story_id is not None else None
        scan_limit = max(limit * 5, limit)
        with self._lock:
            cursor = self.connection.cursor()
            if self._fts_enabled:
                try:
                    if prefix is None:
                        rows = cursor.execute(
                            "SELECT doc_id, content FROM documents_fts WHERE documents_fts MATCH ? LIMIT ?",
                            (query, scan_limit),
                        ).fetchall()
                    else:
                        rows = cursor.execute(
                            "SELECT doc_id, content FROM documents_fts WHERE documents_fts MATCH ? "
                            "AND doc_id LIKE ? LIMIT ?",
                            (query, prefix, scan_limit),
                        ).fetchall()
                    return self._visible_content(rows, max_chapter, limit)
                except sqlite3.OperationalError:
                    pass
            like_query = f"%{query}%"
            if prefix is None:
                rows = cursor.execute(
                    "SELECT doc_id, content FROM documents WHERE content LIKE ? LIMIT ?",
                    (like_query, scan_limit),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT doc_id, content FROM documents WHERE content LIKE ? AND doc_id LIKE ? LIMIT ?",
                    (like_query, prefix, scan_limit),
                ).fetchall()
            return self._visible_content(rows, max_chapter, limit)

    def delete_prefix(self, id_prefix: str) -> int:
        pattern = f"{id_prefix}%"
        with self._lock, self.connection:
            doc_ids = [
                row[0]
                for row in self.connection.execute(
                    "SELECT doc_id FROM documents WHERE doc_id LIKE ?", (pattern,)
                ).fetchall()
            ]
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE doc_id LIKE ?", (pattern,))
            self.connection.execute("DELETE FROM documents WHERE doc_id LIKE ?", (pattern,))
        return len(doc_ids)

    def delete_story(self, story_id: str) -> int:
        return self.delete_prefix(f"{story_id}:")

    def close(self) -> None:
        """Release the SQLite connection owned by this index instance."""
        with self._lock:
            self.connection.close()

    def _visible_content(
        self,
        rows: list[tuple[str, str]],
        max_chapter: int | None,
        limit: int,
    ) -> list[str]:
        return [content for doc_id, content in rows if self._visible(doc_id, max_chapter)][:limit]

    def _visible(self, doc_id: str, max_chapter: int | None) -> bool:
        if max_chapter is None:
            return True
        match = re.search(r":chapter:(\d+)(?::|$)", doc_id)
        return match is None or int(match.group(1)) <= max_chapter

    def _init_schema(self) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS documents("
                "doc_id TEXT PRIMARY KEY, content TEXT NOT NULL)"
            )
            try:
                self.connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts "
                    "USING fts5(doc_id UNINDEXED, content)"
                )
            except sqlite3.OperationalError:
                self._fts_enabled = False
