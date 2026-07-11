"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from novelforge.core.models import CharacterFact, Chapter, ChapterContract, ChapterOutline, ReviewReport, Story


class CreateStoryRequest(BaseModel):
    """创建新故事的请求体。"""

    premise: str
    title: str = "Untitled Novel"
    genre: str = "novel"
    style_guide: str = ""


class OutlineRequest(BaseModel):
    """生成章纲的请求体。"""

    num_chapters: int | None = None
    force: bool = False


class BatchWriteRequest(BaseModel):
    """批量生成章节的请求体。"""

    start_chapter: int
    end_chapter: int
    use_auto_revision: bool = True
    background: bool = True


class AgenticRunRequest(BaseModel):
    """自动代理式写作运行的请求体。"""

    objective: str
    start_chapter: int = 1
    end_chapter: int = 1
    use_auto_revision: bool = True
    background: bool = True


class DirectorRunRequest(BaseModel):
    """Director 代理执行用户指令的请求体。"""

    user_message: str
    max_steps: int = 6


class ReviseRequest(BaseModel):
    """章节修订的请求体。"""

    revised_content: str | None = None


class ChapterContentRequest(BaseModel):
    """更新章节正文的请求体。"""

    title: str | None = None
    content: str
    status: str = "draft"


class ChapterContractRequest(ChapterContract):
    """创建或更新章节合同的请求体。"""

    pass


class CharacterFactRequest(CharacterFact):
    """新增或覆盖用户确认人物事实的请求体。"""

    pass


class StoryResponse(BaseModel):
    """故事详情的响应体。"""

    story: Story


class OutlineResponse(BaseModel):
    """章纲列表的响应体。"""

    outlines: list[ChapterOutline]


class ChapterResponse(BaseModel):
    """单个章节详情的响应体。"""

    chapter: Chapter


class ReviewResponse(BaseModel):
    """评审报告的响应体。"""

    report: ReviewReport


class StatusResponse(BaseModel):
    """故事状态摘要的响应体。"""

    story_id: str
    title: str
    status: str
    current_chapter: int
    extra: dict[str, Any] = {}
