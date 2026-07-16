"""SQLite persistence for operational agent work, separate from Story canon."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from uuid import UUID

from novelforge.domain import (
    AgentRun,
    AgentStep,
    CandidateEvaluationRecord,
    ChapterCandidateRecord,
    RevisionProposal,
)


class AgentRunRepository:
    """Persist resumable runs, tool steps, candidates, and evaluations.

    These records share the physical SQLite database for transactional cleanup,
    but they are not serialized inside the canonical Story aggregate.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_story
                    ON agent_runs(story_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS agent_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    step_json TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_agent_steps_run
                    ON agent_steps(run_id, sequence);

                CREATE TABLE IF NOT EXISTS chapter_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    story_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_run
                    ON chapter_candidates(run_id, chapter_index);

                CREATE TABLE IF NOT EXISTS candidate_evaluations (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    evaluator TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES chapter_candidates(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_evaluations_candidate
                    ON candidate_evaluations(candidate_id);

                CREATE TABLE IF NOT EXISTS revision_proposals (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_revision_proposals_story
                    ON revision_proposals(story_id, chapter_index, updated_at DESC);
                """
            )

    def save_run(self, run: AgentRun) -> AgentRun:
        snapshot = run.model_copy(deep=True)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO agent_runs(
                    id, story_id, status, goal, current_step, updated_at, run_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    goal=excluded.goal,
                    current_step=excluded.current_step,
                    updated_at=excluded.updated_at,
                    run_json=excluded.run_json
                """,
                (
                    str(snapshot.id),
                    str(snapshot.story_id),
                    snapshot.status,
                    snapshot.goal,
                    snapshot.current_step,
                    snapshot.updated_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def load_run(self, run_id: str | UUID) -> AgentRun:
        with self._lock:
            row = self._connection.execute(
                "SELECT run_json FROM agent_runs WHERE id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Agent run {run_id} does not exist.")
        return AgentRun.model_validate_json(row["run_json"])

    def list_runs(self, story_id: str | UUID, limit: int = 50) -> list[AgentRun]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT run_json FROM agent_runs
                WHERE story_id = ? ORDER BY updated_at DESC LIMIT ?
                """,
                (str(story_id), limit),
            ).fetchall()
        return [AgentRun.model_validate_json(row["run_json"]) for row in rows]

    def save_step(self, step: AgentStep) -> AgentStep:
        snapshot = step.model_copy(deep=True)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO agent_steps(
                    id, run_id, sequence, status, tool_name, step_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    tool_name=excluded.tool_name,
                    step_json=excluded.step_json
                """,
                (
                    str(snapshot.id),
                    str(snapshot.run_id),
                    snapshot.sequence,
                    snapshot.status,
                    snapshot.tool_name,
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def list_steps(self, run_id: str | UUID) -> list[AgentStep]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT step_json FROM agent_steps
                WHERE run_id = ? ORDER BY sequence
                """,
                (str(run_id),),
            ).fetchall()
        return [AgentStep.model_validate_json(row["step_json"]) for row in rows]

    def save_candidate(self, candidate: ChapterCandidateRecord) -> ChapterCandidateRecord:
        snapshot = candidate.model_copy(deep=True)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO chapter_candidates(
                    id, run_id, story_id, chapter_index, status, candidate_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    candidate_json=excluded.candidate_json
                """,
                (
                    str(snapshot.id),
                    str(snapshot.run_id),
                    str(snapshot.story_id),
                    snapshot.chapter_index,
                    snapshot.status,
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def load_candidate(self, candidate_id: str | UUID) -> ChapterCandidateRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT candidate_json FROM chapter_candidates WHERE id = ?",
                (str(candidate_id),),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Candidate {candidate_id} does not exist.")
        return ChapterCandidateRecord.model_validate_json(row["candidate_json"])

    def list_candidates(self, run_id: str | UUID) -> list[ChapterCandidateRecord]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT candidate_json FROM chapter_candidates
                WHERE run_id = ? ORDER BY chapter_index, rowid
                """,
                (str(run_id),),
            ).fetchall()
        return [ChapterCandidateRecord.model_validate_json(row["candidate_json"]) for row in rows]

    def add_evaluation(self, evaluation: CandidateEvaluationRecord) -> CandidateEvaluationRecord:
        snapshot = evaluation.model_copy(deep=True)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO candidate_evaluations(
                    id, candidate_id, evaluator, passed, evaluation_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(snapshot.id),
                    str(snapshot.candidate_id),
                    snapshot.evaluator,
                    int(snapshot.passed),
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def list_evaluations(self, candidate_id: str | UUID) -> list[CandidateEvaluationRecord]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT evaluation_json FROM candidate_evaluations
                WHERE candidate_id = ? ORDER BY rowid
                """,
                (str(candidate_id),),
            ).fetchall()
        return [
            CandidateEvaluationRecord.model_validate_json(row["evaluation_json"]) for row in rows
        ]

    def save_revision_proposal(self, proposal: RevisionProposal) -> RevisionProposal:
        snapshot = proposal.model_copy(deep=True)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO revision_proposals(
                    id, story_id, chapter_index, status, updated_at, proposal_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    proposal_json=excluded.proposal_json
                """,
                (
                    snapshot.id,
                    snapshot.story_id,
                    snapshot.chapter_index,
                    snapshot.status,
                    snapshot.updated_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def load_revision_proposal(self, proposal_id: str) -> RevisionProposal:
        with self._lock:
            row = self._connection.execute(
                "SELECT proposal_json FROM revision_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Revision proposal {proposal_id} does not exist.")
        return RevisionProposal.model_validate_json(row["proposal_json"])

    def list_revision_proposals(
        self,
        story_id: str | UUID,
        chapter_index: int | None = None,
    ) -> list[RevisionProposal]:
        query = "SELECT proposal_json FROM revision_proposals WHERE story_id = ?"
        values: list[object] = [str(story_id)]
        if chapter_index is not None:
            query += " AND chapter_index = ?"
            values.append(chapter_index)
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [RevisionProposal.model_validate_json(row["proposal_json"]) for row in rows]

    def delete_story(self, story_id: str | UUID) -> dict[str, int]:
        with self._lock, self._connection:
            proposals = self._connection.execute(
                "DELETE FROM revision_proposals WHERE story_id = ?", (str(story_id),)
            ).rowcount
            runs = self._connection.execute(
                "DELETE FROM agent_runs WHERE story_id = ?", (str(story_id),)
            ).rowcount
        return {"agent_runs": runs, "revision_proposals": proposals}

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["AgentRunRepository"]
