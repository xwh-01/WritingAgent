"""Creative writing agent."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import Beat, ChapterOutline


class WriterAgent(BaseAgent):
    name = "writer"

    def write_chapter(
        self,
        chapter_index: int,
        outline: ChapterOutline,
        beats: list[Beat],
        assembled_context: str,
        style_guide: str = "",
    ) -> str:
        system = (
            "你是成熟的长篇小说作家。按照章节大纲和场景节拍写完整正文。"
            "要求: 叙事连贯、人物行为有因果、结尾有推进或悬念。"
            f"文风指南: {style_guide or '清晰、有画面感、节奏稳定。'}"
        )
        user = (
            f"写第 {chapter_index} 章。\n"
            f"章节大纲: {json.dumps(outline.model_dump(), ensure_ascii=False)}\n"
            f"场景节拍: {json.dumps([beat.model_dump() for beat in beats], ensure_ascii=False)}\n"
            f"上下文: {assembled_context}\n"
            "只输出正文。"
        )
        return self._chat(system, user).strip()
