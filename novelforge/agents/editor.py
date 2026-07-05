"""Editor agent for revision and prose polishing."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import QualityReviewReport, ReviewReport


class EditorAgent(BaseAgent):
    name = "editor"

    def revise_chapter(self, chapter_content: str, review_report: ReviewReport, style_guide: str = "") -> str:
        system = (
            "你是执行力很强的小说编辑。根据审查报告修订全文，保留有效内容，修复问题。"
            f"文风指南: {style_guide or '保持原有叙事风格，增强清晰度和张力。'}"
        )
        user = (
            "revise_chapter 润色并修订以下章节。\n"
            f"审查报告: {json.dumps(review_report.model_dump(), ensure_ascii=False)}\n"
            f"原文: {chapter_content}\n"
            "只输出修订后全文。"
        )
        return self._chat(system, user).strip()

    def polish_prose(self, content: str, instructions: str) -> str:
        system = "你是小说文笔润色编辑。按用户指令改写，不改变核心剧情。"
        return self._chat(system, f"润色指令: {instructions}\n正文: {content}").strip()

    def revise_from_quality_report(
        self,
        chapter_content: str,
        quality_report: QualityReviewReport,
        style_guide: str = "",
    ) -> str:
        system = (
            "你是负责闭环修复的小说编辑。根据质量评分卡逐项修复问题，输出完整修订后正文。"
            "要求：保留原剧情核心，补足逻辑、人设、伏笔、节奏和文风问题。"
            f"文风指南: {style_guide or '保持连贯、清晰、有叙事张力。'}"
        )
        user = (
            "revise_chapter_quality 修订以下章节。\n"
            f"质量评分卡: {json.dumps(quality_report.model_dump(), ensure_ascii=False)}\n"
            f"原文: {chapter_content}\n"
            "只输出修订后全文。"
        )
        return self._chat(system, user).strip()
