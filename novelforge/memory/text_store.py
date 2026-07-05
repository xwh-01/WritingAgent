"""SQLite FTS full-text index for chapters and notes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from novelforge.memory.interfaces import IFTSStore


class SQLiteFTSStore(IFTSStore):
    def __init__(self, sqlite_path: str):
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._fts_enabled = True
        self._init_schema()

    def index_document(self, doc_id: str, content: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO documents(doc_id, content) VALUES (?, ?)",
                (doc_id, content),
            )
            if self._fts_enabled:
                self.connection.execute(
                    "INSERT OR REPLACE INTO documents_fts(rowid, doc_id, content) "
                    "VALUES ((SELECT rowid FROM documents WHERE doc_id = ?), ?, ?)",
                    (doc_id, doc_id, content),
                )

    def search(self, query: str, limit: int = 10) -> list[str]:
        if not query.strip():
            return []
        cursor = self.connection.cursor()
        if self._fts_enabled:
            try:
                rows = cursor.execute(
                    "SELECT content FROM documents_fts WHERE documents_fts MATCH ? LIMIT ?",
                    (query, limit),
                ).fetchall()
                return [row[0] for row in rows]
            except sqlite3.OperationalError:
                pass
        like_query = f"%{query}%"
        rows = cursor.execute(
            "SELECT content FROM documents WHERE content LIKE ? LIMIT ?",
            (like_query, limit),
        ).fetchall()
        return [row[0] for row in rows]

    def delete_story(self, story_id: str) -> int:
        prefix = f"{story_id}:%"
        with self.connection:
            doc_ids = [
                row[0]
                for row in self.connection.execute(
                    "SELECT doc_id FROM documents WHERE doc_id LIKE ?",
                    (prefix,),
                ).fetchall()
            ]
            if self._fts_enabled:
                for doc_id in doc_ids:
                    self.connection.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
            self.connection.execute("DELETE FROM documents WHERE doc_id LIKE ?", (prefix,))
        return len(doc_ids)

    def _init_schema(self) -> None:
        with self.connection:
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
