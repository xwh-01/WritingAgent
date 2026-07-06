"""Story endpoints."""

from __future__ import annotations

from fastapi import APIRouter
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

router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("/", response_model=StoryResponse)
def create_story(payload: CreateStoryRequest) -> StoryResponse:
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
    engine = get_engine(story_id)
    return StoryResponse(story=engine.story)


@router.delete("/{story_id}")
def delete_story(story_id: str) -> dict:
    engine = ENGINES.get(story_id) or NovelForgeEngine()
    result = engine.delete_story_data(story_id)
    ENGINES.pop(story_id, None)
    return {"deleted": bool(result["story_file"]), **result}


@router.post("/{story_id}/outline", response_model=OutlineResponse)
def generate_outline(story_id: str, payload: OutlineRequest) -> OutlineResponse:
    engine = get_engine(story_id)
    return OutlineResponse(outlines=engine.generate_outline(payload.num_chapters, force=payload.force))


@router.post("/{story_id}/batch-write")
def batch_write(story_id: str, payload: BatchWriteRequest) -> dict:
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
    engine = get_engine(story_id)
    return engine.run_director_agent(payload.user_message, payload.max_steps).model_dump()


@router.get("/{story_id}/agent/runs")
def list_director_runs(story_id: str) -> dict:
    engine = get_engine(story_id)
    return {"runs": [run.model_dump() for run in engine.list_director_runs()]}


@router.get("/{story_id}/agent/runs/{run_id}")
def get_director_run(story_id: str, run_id: str) -> dict:
    engine = get_engine(story_id)
    run = engine.get_director_run(run_id)
    if run is None:
        return {"error": "run_not_found", "run_id": run_id}
    return run.model_dump()


@router.get("/{story_id}/status", response_model=StatusResponse)
def get_status(story_id: str) -> StatusResponse:
    engine = get_engine(story_id)
    story = engine.story
    return StatusResponse(
        story_id=str(story.id),
        title=story.title,
        status=story.status,
        current_chapter=story.current_chapter,
        extra={"chapters": len(story.chapters), "outlines": len(story.outlines)},
    )
