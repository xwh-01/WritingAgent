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


class InspectChapterArgs(ChapterIndexArgs):
    """读取章节，可选择是否包含完整正文。"""

    include_content: bool = True


class ReviseChapterArgs(ChapterIndexArgs):
    """revise_chapter 工具的参数模型，继承 ChapterIndexArgs 并增加可选的手动替换内容。"""
    revised_content: str | None = None
    revision_instruction: str | None = None


class ListForeshadowingsArgs(BaseModel):
    """list_foreshadowings 工具的参数模型，可按 status 字段筛选。"""
    status: str | None = None


class CharacterContinuityArgs(BaseModel):
    """跨章节角色连续性审计参数。"""

    character: str = Field(min_length=1)
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)


TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "show_status": EmptyArgs,
    "inspect_chapter": InspectChapterArgs,
    "create_outline": CreateOutlineArgs,
    "create_beats": ChapterIndexArgs,
    "write_chapter": ChapterIndexArgs,
    "review_chapter": ChapterIndexArgs,
    "revise_chapter": ReviseChapterArgs,
    "auto_write_chapter": ChapterIndexArgs,
    "audit_continuity": ChapterIndexArgs,
    "update_memory": ChapterIndexArgs,
    "list_foreshadowings": ListForeshadowingsArgs,
    "analyze_character_continuity": CharacterContinuityArgs,
}
