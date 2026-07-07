"""In-process background job registry for autonomous workflows."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from novelforge.core.models import AutoRevisionReport, AutonomousRunReport, BatchWriteReport


@dataclass
class AutoRevisionJob:
    id: str
    story_id: str
    chapter_index: int
    run_id: str = ""
    status: str = "queued"
    current_round: int = 0
    progress_current: int = 0
    progress_total: int = 0
    message: str = "Queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    result: AutoRevisionReport | None = None
    batch_result: BatchWriteReport | None = None
    autonomous_result: AutonomousRunReport | None = None
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id or self.id,
            "story_id": self.story_id,
            "chapter_index": self.chapter_index,
            "status": self.status,
            "current_round": self.current_round,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "message": self.message,
            "events": self.events,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result": self.result.model_dump() if self.result else None,
            "batch_result": self.batch_result.model_dump() if self.batch_result else None,
            "autonomous_result": self.autonomous_result.model_dump() if self.autonomous_result else None,
        }


class AutoRevisionJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, AutoRevisionJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, engine, story_id: str, chapter_index: int) -> AutoRevisionJob:
        job = AutoRevisionJob(
            id=f"job-{uuid4().hex[:10]}",
            story_id=story_id,
            chapter_index=chapter_index,
            run_id=f"auto-revision:{story_id}:ch{chapter_index}",
            progress_total=1,
            message=f"Queued auto-revision for chapter {chapter_index}",
        )
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
            run_id=f"batch:{story_id}:ch{start_chapter}-{end_chapter}",
            progress_total=max(0, end_chapter - start_chapter + 1),
            message=f"Queued batch writing for chapters {start_chapter}-{end_chapter}",
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

    def start_agentic_run(
        self,
        engine,
        story_id: str,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool = True,
    ) -> AutoRevisionJob:
        job = AutoRevisionJob(
            id=f"job-{uuid4().hex[:10]}",
            story_id=story_id,
            chapter_index=start_chapter,
            run_id=f"agentic:{story_id}:ch{start_chapter}-{end_chapter}",
            progress_total=0,
            message=f"Queued agentic writing run for chapters {start_chapter}-{end_chapter}",
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._run_agentic,
            args=(job.id, engine, objective, start_chapter, end_chapter, use_auto_revision),
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
            self.record_progress(
                job_id,
                "Starting auto-revision",
                progress_current=0,
                progress_total=1,
                status="running",
                chapter_index=job.chapter_index,
                stage="start",
            )
            result = engine.auto_write_chapter(job.chapter_index)
            status = "passed" if result.passed else "stopped" if result.stopped else "finished_with_residual_issues"
            self.record_progress(
                job_id,
                f"Chapter {job.chapter_index} auto-revision finished",
                progress_current=1,
                progress_total=1,
                chapter_index=job.chapter_index,
                stage="finished",
            )
            self._update(job_id, status=status, result=result, current_round=len(result.rounds))
        except Exception as exc:
            self.record_progress(job_id, f"Auto-revision failed: {exc}", status="failed", stage="failed")
            self._update(job_id, status="failed", error=str(exc), message=str(exc))

    def _run_batch(
        self,
        job_id: str,
        engine,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> None:
        try:
            total = max(0, end_chapter - start_chapter + 1)
            self.record_progress(
                job_id,
                f"Starting batch writing for chapters {start_chapter}-{end_chapter}",
                progress_current=0,
                progress_total=total,
                status="running_batch",
                stage="start",
            )

            def progress_callback(event: dict[str, object]) -> None:
                current = event.get("progress_current")
                total = event.get("progress_total")
                chapter = event.get("chapter_index")
                status = event.get("status")
                stage = event.get("stage")
                self.record_progress(
                    job_id,
                    str(event.get("message") or "Working"),
                    progress_current=current if isinstance(current, int) else None,
                    progress_total=total if isinstance(total, int) else None,
                    status=status if isinstance(status, str) else None,
                    chapter_index=chapter if isinstance(chapter, int) else None,
                    stage=stage if isinstance(stage, str) else None,
                )

            result = engine.batch_write_chapters(
                start_chapter,
                end_chapter,
                use_auto_revision,
                progress_callback=progress_callback,
            )
            status = "batch_finished" if result.failed == 0 else "batch_finished_with_failures"
            self.record_progress(
                job_id,
                f"Batch finished: {result.completed} completed, {result.failed} failed",
                progress_current=result.completed,
                progress_total=total,
                status=status,
                stage="finished",
            )
            self._update(job_id, status=status, batch_result=result, current_round=result.completed)
        except Exception as exc:
            self.record_progress(job_id, f"Batch failed: {exc}", status="failed", stage="failed")
            self._update(job_id, status="failed", error=str(exc), message=str(exc))

    def _run_agentic(
        self,
        job_id: str,
        engine,
        objective: str,
        start_chapter: int,
        end_chapter: int,
        use_auto_revision: bool,
    ) -> None:
        try:
            self.record_progress(
                job_id,
                f"Starting agentic writing run for chapters {start_chapter}-{end_chapter}",
                progress_current=0,
                status="running_agentic",
                stage="start",
            )

            def progress_callback(event: dict[str, object]) -> None:
                current = event.get("progress_current")
                total = event.get("progress_total")
                chapter = event.get("chapter_index")
                status = event.get("status")
                stage = event.get("stage")
                self.record_progress(
                    job_id,
                    str(event.get("message") or "Working"),
                    progress_current=current if isinstance(current, int) else None,
                    progress_total=total if isinstance(total, int) else None,
                    status=status if isinstance(status, str) else None,
                    chapter_index=chapter if isinstance(chapter, int) else None,
                    stage=stage if isinstance(stage, str) else None,
                    agent=event.get("agent") if isinstance(event.get("agent"), str) else None,
                    action=event.get("action") if isinstance(event.get("action"), str) else None,
                    task_id=event.get("task_id") if isinstance(event.get("task_id"), str) else None,
                    run_id=event.get("run_id") if isinstance(event.get("run_id"), str) else None,
                )

            result = engine.agentic_writing_run(
                objective,
                start_chapter,
                end_chapter,
                use_auto_revision,
                progress_callback=progress_callback,
            )
            status = "agentic_finished" if result.failed_tasks == 0 else "agentic_finished_with_failures"
            self.record_progress(
                job_id,
                result.summary,
                progress_current=result.completed_tasks,
                progress_total=len(result.tasks),
                status=status,
                stage="finished",
            )
            self._update(job_id, status=status, autonomous_result=result, current_round=result.completed_tasks)
        except Exception as exc:
            self.record_progress(job_id, f"Agentic run failed: {exc}", status="failed", stage="failed")
            self._update(job_id, status="failed", error=str(exc), message=str(exc))

    def record_progress(
        self,
        job_id: str,
        message: str,
        progress_current: int | None = None,
        progress_total: int | None = None,
        status: str | None = None,
        chapter_index: int | None = None,
        stage: str | None = None,
        agent: str | None = None,
        action: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            now = datetime.now(timezone.utc)
            if status is not None:
                job.status = status
            if progress_current is not None:
                job.progress_current = int(progress_current)
                job.current_round = int(progress_current)
            if progress_total is not None:
                job.progress_total = int(progress_total)
            job.message = message
            event = {
                "time": now.isoformat(),
                "message": message,
                "chapter_index": chapter_index,
                "stage": stage,
                "agent": agent,
                "action": action,
                "task_id": task_id,
                "run_id": run_id or job.run_id or job.id,
                "progress_current": job.progress_current,
                "progress_total": job.progress_total,
            }
            job.events.append(event)
            if len(job.events) > 120:
                del job.events[:-120]
            job.updated_at = now

    def _update(
        self,
        job_id: str,
        status: str | None = None,
        result: AutoRevisionReport | None = None,
        batch_result: BatchWriteReport | None = None,
        autonomous_result: AutonomousRunReport | None = None,
        current_round: int | None = None,
        error: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if batch_result is not None:
                job.batch_result = batch_result
            if autonomous_result is not None:
                job.autonomous_result = autonomous_result
            if current_round is not None:
                job.current_round = current_round
            if error is not None:
                job.error = error
            if message is not None:
                job.message = message
            job.updated_at = datetime.now(timezone.utc)
