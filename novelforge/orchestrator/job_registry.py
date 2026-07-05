"""In-process background job registry for autonomous workflows."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from novelforge.core.models import AutoRevisionReport, BatchWriteReport


@dataclass
class AutoRevisionJob:
    id: str
    story_id: str
    chapter_index: int
    status: str = "queued"
    current_round: int = 0
    result: AutoRevisionReport | None = None
    batch_result: BatchWriteReport | None = None
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "story_id": self.story_id,
            "chapter_index": self.chapter_index,
            "status": self.status,
            "current_round": self.current_round,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result": self.result.model_dump() if self.result else None,
            "batch_result": self.batch_result.model_dump() if self.batch_result else None,
        }


class AutoRevisionJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, AutoRevisionJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, engine, story_id: str, chapter_index: int) -> AutoRevisionJob:
        job = AutoRevisionJob(id=f"job-{uuid4().hex[:10]}", story_id=story_id, chapter_index=chapter_index)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id, engine), daemon=True)
        with self._lock:
            self._threads[job.id] = thread
        thread.start()
        return job

    def start_batch(
        self,
        engine,
        story_id: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
    ) -> AutoRevisionJob:
        job = AutoRevisionJob(
            id=f"job-{uuid4().hex[:10]}",
            story_id=story_id,
            chapter_index=start_chapter,
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._run_batch,
            args=(job.id, engine, start_chapter, end_chapter, use_auto_revision),
            daemon=True,
        )
        with self._lock:
            self._threads[job.id] = thread
        thread.start()
        return job

    def get(self, job_id: str) -> AutoRevisionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_story(self, story_id: str) -> list[AutoRevisionJob]:
        with self._lock:
            return [job for job in self._jobs.values() if job.story_id == story_id]

    def request_stop(self, job_id: str, engine) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        stopped = engine.stop_auto_revision()
        with self._lock:
            job.status = "stop_requested" if stopped else job.status
            job.updated_at = datetime.now(timezone.utc)
        return stopped

    def _run(self, job_id: str, engine) -> None:
        job = self.get(job_id)
        if job is None:
            return
        try:
            self._update(job_id, status="running")
            result = engine.auto_write_chapter(job.chapter_index)
            status = "passed" if result.passed else "stopped" if result.stopped else "finished_with_residual_issues"
            self._update(job_id, status=status, result=result, current_round=len(result.rounds))
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))

    def _run_batch(
        self,
        job_id: str,
        engine,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> None:
        try:
            self._update(job_id, status="running_batch")
            result = engine.batch_write_chapters(start_chapter, end_chapter, use_auto_revision)
            status = "batch_finished" if result.failed == 0 else "batch_finished_with_failures"
            self._update(job_id, status=status, batch_result=result, current_round=result.completed)
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))

    def _update(
        self,
        job_id: str,
        status: str | None = None,
        result: AutoRevisionReport | None = None,
        batch_result: BatchWriteReport | None = None,
        current_round: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if batch_result is not None:
                job.batch_result = batch_result
            if current_round is not None:
                job.current_round = current_round
            if error is not None:
                job.error = error
            job.updated_at = datetime.now(timezone.utc)
