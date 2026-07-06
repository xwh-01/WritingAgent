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
            "你是成熟的长篇小说作家，负责写可直接发布的章节正文，不是大纲扩写。"
            "写作要求：\n"
            "1. 按场景推进，用具体动作、对话、环境细节和心理变化承载剧情。\n"
            "2. 不要用“本章讲述/随后发生/他经历了”等摘要式句子跳过关键戏剧段落。\n"
            "3. 每个场景必须有目标、阻力、转折和结果，人物选择要有可见代价。\n"
            "4. 语言要有节奏和画面感，避免流水账、口号、空泛热血和重复形容。\n"
            "5. 结尾要留下情绪余波、信息钩子或局势推进。\n"
            f"文风指南: {style_guide or '清晰克制，有临场感，动作和心理交织，长篇连载节奏。'}"
        )
        user = (
            f"写第 {chapter_index} 章。\n"
            f"章节大纲: {json.dumps(outline.model_dump(), ensure_ascii=False)}\n"
            f"场景节拍: {json.dumps([beat.model_dump() for beat in beats], ensure_ascii=False)}\n"
            f"上下文: {assembled_context}\n"
            "输出要求：\n"
            "- 只输出小说正文，不要解释创作思路。\n"
            "- 正文应包含完整场景，不要写成提纲或摘要。\n"
            "- 优先写出人物在压力中的具体反应，而不是直接评价人物。\n"
        )
        return self._chat(system, user).strip()
