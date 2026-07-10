"""Typed input schemas for Director tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmptyArgs(BaseModel):
    """空参数模型，用于无参数工具（如 show_status）。"""


class CreateOutlineArgs(BaseModel):
    """创建大纲的参数模型，可选章节数量（>=1）。"""
    num_chapters: int | None = Field(default=None, ge=1)


class ChapterIndexArgs(BaseModel):
    """单章节索引参数模型，要求 chapter_index >= 1。"""
    chapter_index: int = Field(ge=1)


class ReviseChapterArgs(ChapterIndexArgs):
    """revise_chapter 工具的参数模型，继承 ChapterIndexArgs 并增加可选的手动替换内容。"""
    revised_content: str | None = None


class ListForeshadowingsArgs(BaseModel):
    """list_foreshadowings 工具的参数模型，可按 status 字段筛选。"""
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
