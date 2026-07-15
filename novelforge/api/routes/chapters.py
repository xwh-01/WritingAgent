"""Chapter planning, generation, review, and edit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from novelforge.api.schemas import (
    ChapterContentRequest,
    ChapterContractRequest,
    ChapterResponse,
    ReviewResponse,
    RevisionRequest,
)
from novelforge.api.state import get_engine

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/{chapter_index}/", response_model=ChapterResponse)
def get_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    chapter = get_engine(story_id).current_story.require_chapter(chapter_index)
    return ChapterResponse(chapter=chapter)


@router.get("/{chapter_index}/contract")
def get_contract(
    chapter_index: int,
    story_id: str = Query(...),
    force: bool = Query(default=False),
) -> dict:
    return get_engine(story_id).ensure_chapter_contract(chapter_index, force).model_dump()


@router.put("/{chapter_index}/contract")
def update_contract(
    chapter_index: int,
    payload: ChapterContractRequest,
    story_id: str = Query(...),
) -> dict:
    return get_engine(story_id).update_chapter_contract(chapter_index, payload).model_dump()


@router.post("/{chapter_index}/beats", response_model=ChapterResponse)
def generate_beats(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).generate_beats(chapter_index))


@router.post("/{chapter_index}/write", response_model=ChapterResponse)
def write_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).write_chapter(chapter_index))


@router.post("/{chapter_index}/review", response_model=ReviewResponse)
def review_chapter(chapter_index: int, story_id: str = Query(...)) -> ReviewResponse:
    return ReviewResponse(report=get_engine(story_id).request_review(chapter_index))


@router.post("/{chapter_index}/validate-contract")
def validate_contract(chapter_index: int, story_id: str = Query(...)) -> dict:
    checks = get_engine(story_id).validate_chapter_contract(chapter_index)
    return {
        "passed": all(check.passed for check in checks),
        "checks": [check.model_dump() for check in checks],
    }


@router.post("/{chapter_index}/audit")
def audit_continuity(chapter_index: int, story_id: str = Query(...)) -> dict:
    return get_engine(story_id).audit_chapter_continuity(chapter_index).model_dump()


@router.put("/{chapter_index}/content", response_model=ChapterResponse)
def update_content(
    chapter_index: int,
    payload: ChapterContentRequest,
    story_id: str = Query(...),
) -> ChapterResponse:
    chapter = get_engine(story_id).update_chapter_content(
        chapter_index,
        payload.content,
        payload.title,
        payload.status,
    )
    return ChapterResponse(chapter=chapter)


@router.post("/{chapter_index}/revision-proposals")
def create_revision_proposal(
    chapter_index: int,
    payload: RevisionRequest,
    story_id: str = Query(...),
) -> dict:
    return (
        get_engine(story_id)
        .create_revision_proposal(
            chapter_index,
            payload.instruction,
        )
        .model_dump()
    )


@router.post("/{chapter_index}/finalize", response_model=ChapterResponse)
def finalize_chapter(chapter_index: int, story_id: str = Query(...)) -> ChapterResponse:
    return ChapterResponse(chapter=get_engine(story_id).finalize_chapter(chapter_index))


@router.get("/{chapter_index}/report")
def get_generation_report(chapter_index: int, story_id: str = Query(...)) -> dict:
    story = get_engine(story_id).current_story
    report = story.quality.generation_reports.get(chapter_index)
    continuity = story.quality.continuity_reports.get(chapter_index)
    review = story.quality.review_reports.get(chapter_index)
    return {
        "generation": report.model_dump() if report else None,
        "continuity": continuity.model_dump() if continuity else None,
        "review": review.model_dump() if review else None,
    }
