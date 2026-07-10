"""Chapter workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from novelforge.api.schemas import ChapterContentRequest, ChapterResponse, ReviewResponse, ReviseRequest
from novelforge.api.state import AUTO_REVISION_JOBS, get_engine
from novelforge.storage.repository import StoryRepository

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/auto/status")
def get_auto_status(story_id: str = Query(...), job_id: str | None = Query(default=None)) -> dict[str, object]:
    """GET /chapters/auto/status — 查询自动修订循环的当前状态或指定任务状态。"""
    if job_id:
        job = AUTO_REVISION_JOBS.get(job_id)
        return job.to_dict() if job else {"status": "not_found", "job_id": job_id}
    return get_engine(story_id).get_auto_status()


@router.post("/auto/stop")
def stop_auto_revision(story_id: str = Query(...), job_id: str | None = Query(default=None)) -> dict[str, bool]:
    """POST /chapters/auto/stop — 请求停止正在运行的自动修订任务。"""
    engine = get_engine(story_id)
    if job_id:
        return {"stop_requested": AUTO_REVISION_JOBS.request_stop(job_id, engine)}
    return {"stop_requested": engine.stop_auto_revision()}


@router.get("/{chapter_index}/", response_model=ChapterResponse)
def get_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    """GET /chapters/{chapter_index}/ — 获取指定章节的完整信息。"""
    engine = get_engine(story_id)
    chapter = engine.story.chapters[chapter_index]
    return ChapterResponse(chapter=chapter)


@router.post("/{chapter_index}/beats", response_model=ChapterResponse)
def generate_beats(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    """POST /chapters/{chapter_index}/beats — 为指定章节生成场景节拍。"""
    return ChapterResponse(chapter=get_engine(story_id).generate_beats(chapter_index))


@router.post("/{chapter_index}/write", response_model=ChapterResponse)
def write_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    """POST /chapters/{chapter_index}/write — 撰写指定章节的初稿。"""
    return ChapterResponse(chapter=get_engine(story_id).write_chapter(chapter_index))


@router.post("/{chapter_index}/review", response_model=ReviewResponse)
def review_chapter(chapter_index: int, story_id: str = Query(...)) -> ReviewResponse:
    """POST /chapters/{chapter_index}/review — 对指定章节进行 AI 评审并返回报告。"""
    return ReviewResponse(report=get_engine(story_id).request_review(chapter_index))


@router.post("/{chapter_index}/audit")
def audit_chapter_continuity(chapter_index: int, story_id: str = Query(...)) -> dict:
    """POST /chapters/{chapter_index}/audit — 对指定章节进行连续性审计。"""
    return get_engine(story_id).audit_chapter_continuity(chapter_index).model_dump()


@router.put("/{chapter_index}/revise", response_model=ChapterResponse)
def revise_chapter(chapter_index: int, payload: ReviseRequest, story_id: str = Query(...)) -> ChapterResponse:
    """PUT /chapters/{chapter_index}/revise — 根据修订请求修订指定章节。"""
    return ChapterResponse(chapter=get_engine(story_id).apply_revision(chapter_index, payload.revised_content))


@router.put("/{chapter_index}/content", response_model=ChapterResponse)
def update_chapter_content(
    chapter_index: int,
    payload: ChapterContentRequest,
    story_id: str = Query(...),
) -> ChapterResponse:
    """PUT /chapters/{chapter_index}/content — 直接更新章节的标题、正文和状态。"""
    chapter = get_engine(story_id).update_chapter_content(
        chapter_index,
        content=payload.content,
        title=payload.title,
        status=payload.status,
    )
    return ChapterResponse(chapter=chapter)


@router.post("/{chapter_index}/auto-write")
def auto_write_chapter(
    chapter_index: int,
    story_id: str = Query(...),
    background: bool = Query(default=False),
) -> dict:
    """POST /chapters/{chapter_index}/auto-write — 自动对章节执行撰写、评审、修订的完整循环，支持后台运行。"""
    engine = get_engine(story_id)
    if background:
        job = AUTO_REVISION_JOBS.start(engine, story_id, chapter_index)
        return job.to_dict()
    result = engine.auto_write_chapter(chapter_index)
    return result.model_dump()


@router.get("/{chapter_index}/report")
def get_auto_revision_report(chapter_index: int, story_id: str = Query(...)) -> dict:
    """GET /chapters/{chapter_index}/report — 获取章节的自动修订测试报告（JSON 格式）。"""
    engine = get_engine(story_id)
    report = engine.story.auto_revision_reports.get(chapter_index)
    continuity = engine.story.continuity_reports.get(chapter_index)
    if report:
        payload = report.model_dump()
        payload["continuity_report"] = continuity.model_dump() if continuity else None
        return payload
    if continuity:
        return {"continuity_report": continuity.model_dump()}
    return {"error": "report_not_found"}


@router.get("/{chapter_index}/report.md", response_class=PlainTextResponse)
def get_auto_revision_report_markdown(chapter_index: int, story_id: str = Query(...)) -> str:
    """GET /chapters/{chapter_index}/report.md — 获取章节的自动修订报告（Markdown 格式）。"""
    engine = get_engine(story_id)
    report = engine.story.auto_revision_reports.get(chapter_index)
    if report is None:
        return "No auto-revision report found."
    return StoryRepository().format_auto_revision_report(engine.story, report)
