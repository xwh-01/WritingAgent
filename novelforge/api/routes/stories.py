"""Story endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from novelforge.api.schemas import CreateStoryRequest, OutlineRequest, OutlineResponse, StatusResponse, StoryResponse
from novelforge.api.state import ENGINES, get_engine
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


@router.post("/{story_id}/outline", response_model=OutlineResponse)
def generate_outline(story_id: str, payload: OutlineRequest) -> OutlineResponse:
    engine = get_engine(story_id)
    return OutlineResponse(outlines=engine.generate_outline(payload.num_chapters))


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
