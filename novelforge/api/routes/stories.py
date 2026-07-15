"""Story aggregate, storage, and batch-use-case endpoints."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from novelforge.api.schemas import (
    BatchWriteRequest,
    CharacterFactRequest,
    CharacterRequest,
    CreateStoryRequest,
    OutlineRequest,
    OutlineResponse,
    StatusResponse,
    StoryResponse,
    WorldSettingRequest,
)
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
    return StoryResponse(story=get_engine(story_id).current_story)


@router.delete("/{story_id}")
def delete_story(story_id: str) -> dict:
    engine = ENGINES.get(story_id) or NovelForgeEngine()
    result = engine.delete_story_data(story_id)
    ENGINES.pop(story_id, None)
    return result


@router.get("/{story_id}/status", response_model=StatusResponse)
def get_status(story_id: str) -> StatusResponse:
    story = get_engine(story_id).current_story
    return StatusResponse(
        story_id=str(story.id),
        title=story.title,
        status=story.status,
        current_chapter=story.current_chapter,
        extra={
            "chapters": len(story.manuscript.chapters),
            "outlines": len(story.design.outlines),
        },
    )


@router.get("/{story_id}/storage")
def get_storage_status(story_id: str) -> dict:
    return get_engine(story_id).storage_status(story_id)


@router.post("/{story_id}/indexes/rebuild")
def rebuild_indexes(story_id: str) -> dict:
    return get_engine(story_id).rebuild_derived_indexes(story_id)


@router.post("/{story_id}/outline", response_model=OutlineResponse)
def generate_outline(story_id: str, payload: OutlineRequest) -> OutlineResponse:
    outlines = get_engine(story_id).generate_outline(
        payload.num_chapters,
        force=payload.force,
    )
    return OutlineResponse(outlines=outlines)


@router.post("/{story_id}/batch-write")
def batch_write(story_id: str, payload: BatchWriteRequest) -> dict:
    if payload.end_chapter < payload.start_chapter:
        raise HTTPException(status_code=422, detail="Invalid chapter range.")
    return (
        get_engine(story_id)
        .batch_write_chapters(
            payload.start_chapter,
            payload.end_chapter,
        )
        .model_dump()
    )


@router.get("/{story_id}/facts")
def list_character_facts(story_id: str, chapter_index: int | None = None) -> dict:
    facts = get_engine(story_id).list_character_facts(chapter_index)
    return {"facts": [fact.model_dump() for fact in facts]}


@router.post("/{story_id}/facts")
def upsert_character_fact(story_id: str, payload: CharacterFactRequest) -> dict:
    return get_engine(story_id).upsert_character_fact(payload).model_dump()


@router.put("/{story_id}/characters/{character_id}")
def upsert_character(
    story_id: str,
    character_id: str,
    payload: CharacterRequest,
) -> dict:
    character = payload.model_copy(update={"id": character_id})
    return get_engine(story_id).upsert_character(character).model_dump()


@router.put("/{story_id}/world/{setting_id}")
def upsert_world_setting(
    story_id: str,
    setting_id: str,
    payload: WorldSettingRequest,
) -> dict:
    setting = payload.model_copy(update={"id": setting_id})
    return get_engine(story_id).upsert_world_setting(setting).model_dump()


@router.delete("/{story_id}/facts/{fact_id}")
def delete_character_fact(story_id: str, fact_id: str) -> dict:
    if not get_engine(story_id).delete_character_fact(fact_id):
        raise HTTPException(status_code=404, detail="Confirmed fact not found.")
    return {"deleted": True, "fact_id": fact_id}


@router.get("/{story_id}/revision-proposals/{proposal_id}")
def get_revision_proposal(story_id: str, proposal_id: str) -> dict:
    proposal = get_engine(story_id).get_revision_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Revision proposal not found.")
    return proposal.model_dump()


@router.post("/{story_id}/revision-proposals/{proposal_id}/accept")
def accept_revision_proposal(story_id: str, proposal_id: str) -> dict:
    chapter = get_engine(story_id).accept_revision_proposal(proposal_id)
    return {"accepted": True, "chapter": chapter.model_dump()}


@router.post("/{story_id}/revision-proposals/{proposal_id}/reject")
def reject_revision_proposal(story_id: str, proposal_id: str) -> dict:
    return get_engine(story_id).reject_revision_proposal(proposal_id).model_dump()


@router.get("/{story_id}/export-docx")
def export_docx(story_id: str) -> FileResponse:
    path = get_engine(story_id).export_docx()
    filename = quote(path.name)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
