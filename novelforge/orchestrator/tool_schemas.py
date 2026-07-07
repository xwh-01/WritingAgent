"""Typed input schemas for Director tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmptyArgs(BaseModel):
    pass


class CreateOutlineArgs(BaseModel):
    num_chapters: int | None = Field(default=None, ge=1)


class ChapterIndexArgs(BaseModel):
    chapter_index: int = Field(ge=1)


class ReviseChapterArgs(ChapterIndexArgs):
    revised_content: str | None = None


class ListForeshadowingsArgs(BaseModel):
    status: str | None = None


TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "show_status": EmptyArgs,
    "create_outline": CreateOutlineArgs,
    "create_beats": ChapterIndexArgs,
    "write_chapter": ChapterIndexArgs,
    "review_chapter": ChapterIndexArgs,
    "revise_chapter": ReviseChapterArgs,
    "auto_write_chapter": ChapterIndexArgs,
    "audit_continuity": ChapterIndexArgs,
    "update_memory": ChapterIndexArgs,
    "list_foreshadowings": ListForeshadowingsArgs,
}
