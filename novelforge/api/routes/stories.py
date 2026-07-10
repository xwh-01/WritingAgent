"""Story endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from novelforge.api.schemas import (
    AgenticRunRequest,
    BatchWriteRequest,
    CreateStoryRequest,
    DirectorRunRequest,
    OutlineRequest,
    OutlineResponse,
    StatusResponse,
    StoryResponse,
)
from novelforge.api.state import AUTO_REVISION_JOBS, ENGINES, get_engine
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.orchestrator.trace_exporter import render_debug_report, trace_to_json

router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("/", response_model=StoryResponse)
def create_story(payload: CreateStoryRequest) -> StoryResponse:
    """POST /stories/ — 创建一个新故事，返回故事详情。"""
    engine = NovelForgeEngine()
    story = engine.start_new_story(
        premise=payload.premise,
        title=payload.title,
        genre=payload.genre,
        style_guide=payload.style_guide,
    )
    ENGINES[str(story.id)] = engine
    return StoryResponse(story=story)


@router.get("/{story_id}/", response_model=StoryResponse)
def get_story(story_id: str) -> StoryResponse:
    """GET /stories/{story_id}/ — 获取指定故事的完整信息。"""
    engine = get_engine(story_id)
    return StoryResponse(story=engine.story)


@router.delete("/{story_id}")
def delete_story(story_id: str) -> dict:
    """DELETE /stories/{story_id} — 删除指定故事及其所有数据文件。"""
    engine = ENGINES.get(story_id) or NovelForgeEngine()
    result = engine.delete_story_data(story_id)
    ENGINES.pop(story_id, None)
    return {"deleted": bool(result["story_file"]), **result}


@router.post("/{story_id}/outline", response_model=OutlineResponse)
def generate_outline(story_id: str, payload: OutlineRequest) -> OutlineResponse:
    """POST /stories/{story_id}/outline — 为指定故事生成章节大纲。"""
    engine = get_engine(story_id)
    return OutlineResponse(outlines=engine.generate_outline(payload.num_chapters, force=payload.force))


@router.post("/{story_id}/batch-write")
def batch_write(story_id: str, payload: BatchWriteRequest) -> dict:
    """POST /stories/{story_id}/batch-write — 批量撰写一个章节区间，支持后台异步执行。"""
    engine = get_engine(story_id)
    if payload.background:
        job = AUTO_REVISION_JOBS.start_batch(
            engine,
            story_id,
            payload.start_chapter,
            payload.end_chapter,
            payload.use_auto_revision,
        )
        return job.to_dict()
    return engine.batch_write_chapters(
        payload.start_chapter,
        payload.end_chapter,
        payload.use_auto_revision,
    ).model_dump()


@router.post("/{story_id}/agentic-run")
def agentic_writing_run(story_id: str, payload: AgenticRunRequest) -> dict:
    """POST /stories/{story_id}/agentic-run — 启动代理自动写作运行，支持后台异步执行。"""
    engine = get_engine(story_id)
    if payload.background:
        job = AUTO_REVISION_JOBS.start_agentic_run(
            engine,
            story_id,
            payload.objective,
            payload.start_chapter,
            payload.end_chapter,
            payload.use_auto_revision,
        )
        return job.to_dict()
    return engine.agentic_writing_run(
        payload.objective,
        payload.start_chapter,
        payload.end_chapter,
        payload.use_auto_revision,
    ).model_dump()


@router.post("/{story_id}/agent/run")
def run_director_agent(story_id: str, payload: DirectorRunRequest) -> dict:
    """POST /stories/{story_id}/agent/run — 让 Director 代理执行一条自然语言指令并返回运行轨迹。"""
    engine = get_engine(story_id)
    return engine.run_director_agent(payload.user_message, payload.max_steps).model_dump()


@router.get("/{story_id}/agent/runs")
def list_director_runs(story_id: str) -> dict:
    """GET /stories/{story_id}/agent/runs — 列出该故事的所有 Director 代理运行记录。"""
    engine = get_engine(story_id)
    return {"runs": [run.model_dump() for run in engine.list_director_runs()]}


@router.get("/{story_id}/agent/runs/{run_id}")
def get_director_run(story_id: str, run_id: str) -> dict:
    """GET /stories/{story_id}/agent/runs/{run_id} — 获取单次 Director 代理运行的详细记录。"""
    engine = get_engine(story_id)
    run = engine.get_director_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Director trace run not found: {run_id}")
    return run.model_dump()


@router.get("/{story_id}/agent/runs/{run_id}/trace.json")
def get_director_trace_json(story_id: str, run_id: str) -> dict:
    """GET /stories/{story_id}/agent/runs/{run_id}/trace.json — 导出单次运行的跟踪数据为 JSON 格式。"""
    engine = get_engine(story_id)
    run = engine.get_director_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Director trace run not found: {run_id}")
    return trace_to_json(run)


@router.get("/{story_id}/agent/runs/{run_id}/debug.md", response_class=PlainTextResponse)
def get_director_debug_markdown(story_id: str, run_id: str) -> str:
    """GET /stories/{story_id}/agent/runs/{run_id}/debug.md — 将单次运行的跟踪数据渲染为 Markdown 调试报告。"""
    engine = get_engine(story_id)
    run = engine.get_director_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Director trace run not found: {run_id}")
    return render_debug_report(run)


@router.get("/{story_id}/status", response_model=StatusResponse)
def get_status(story_id: str) -> StatusResponse:
    """GET /stories/{story_id}/status — 获取故事当前状态的摘要信息。"""
    engine = get_engine(story_id)
    story = engine.story
    return StatusResponse(
        story_id=str(story.id),
        title=story.title,
        status=story.status,
        current_chapter=story.current_chapter,
        extra={"chapters": len(story.chapters), "outlines": len(story.outlines)},
    )


@router.get("/{story_id}/export-docx")
def export_docx(story_id: str):
    """GET /stories/{story_id}/export-docx — 将故事导出为 DOCX 文件并提供下载。"""
    from urllib.parse import quote

    engine = get_engine(story_id)
    path = engine.export_docx()
    filename = quote(path.name)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
