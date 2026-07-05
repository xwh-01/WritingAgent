"""Chapter workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from novelforge.api.schemas import ChapterResponse, ReviewResponse, ReviseRequest
from novelforge.api.state import AUTO_REVISION_JOBS, get_engine
from novelforge.storage.repository import StoryRepository

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/auto/status")
def get_auto_status(story_id: str = Query(...), job_id: str | None = Query(default=None)) -> dict[str, object]:
    if job_id:
        job = AUTO_REVISION_JOBS.get(job_id)
        return job.to_dict() if job else {"status": "not_found", "job_id": job_id}
    return get_engine(story_id).get_auto_status()


@router.post("/auto/stop")
def stop_auto_revision(story_id: str = Query(...), job_id: str | None = Query(default=None)) -> dict[str, bool]:
    engine = get_engine(story_id)
    if job_id:
        return {"stop_requested": AUTO_REVISION_JOBS.request_stop(job_id, engine)}
    return {"stop_requested": engine.stop_auto_revision()}


@router.get("/{chapter_index}/", response_model=ChapterResponse)
def get_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    engine = get_engine(story_id)
    chapter = engine.story.chapters[chapter_index]
    return ChapterResponse(chapter=chapter)


@router.post("/{chapter_index}/beats", response_model=ChapterResponse)
def generate_beats(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).generate_beats(chapter_index))


@router.post("/{chapter_index}/write", response_model=ChapterResponse)
def write_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).write_chapter(chapter_index))


@router.post("/{chapter_index}/review", response_model=ReviewResponse)
def review_chapter(chapter_index: int, story_id: str = Query(...)) -> ReviewResponse:
    return ReviewResponse(report=get_engine(story_id).request_review(chapter_index))


@router.put("/{chapter_index}/revise", response_model=ChapterResponse)
def revise_chapter(chapter_index: int, payload: ReviseRequest, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).apply_revision(chapter_index, payload.revised_content))


@router.post("/{chapter_index}/auto-write")
def auto_write_chapter(
    chapter_index: int,
    story_id: str = Query(...),
    background: bool = Query(default=False),
) -> dict:
    engine = get_engine(story_id)
    if background:
        job = AUTO_REVISION_JOBS.start(engine, story_id, chapter_index)
        return job.to_dict()
    result = engine.auto_write_chapter(chapter_index)
    return result.model_dump()


@router.get("/{chapter_index}/report")
def get_auto_revision_report(chapter_index: int, story_id: str = Query(...)) -> dict:
    engine = get_engine(story_id)
    report = engine.story.auto_revision_reports.get(chapter_index)
    return report.model_dump() if report else {"error": "report_not_found"}


@router.get("/{chapter_index}/report.md", response_class=PlainTextResponse)
def get_auto_revision_report_markdown(chapter_index: int, story_id: str = Query(...)) -> str:
    engine = get_engine(story_id)
    report = engine.story.auto_revision_reports.get(chapter_index)
    if report is None:
        return "No auto-revision report found."
    return StoryRepository().format_auto_revision_report(engine.story, report)
