"""Editor agent for revision and prose polishing."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import QualityReviewReport, ReviewReport


class EditorAgent(BaseAgent):
    """编辑 Agent，根据审查报告修订和润色章节文本。"""

    name = "editor"

    def revise_chapter(
        self,
        chapter_content: str,
        review_report: ReviewReport,
        style_guide: str = "",
        revision_instruction: str = "",
    ) -> str:
        """根据审查报告修订章节全文，输出修订后正文。"""
        system = (
            "你是执行力很强的小说编辑。根据审查报告修订全文，保留有效内容，修复问题。"
            "用户的具体修改要求优先于通用润色要求，但不得破坏明确的故事事实。"
            f"文风指南: {style_guide or '保持原有叙事风格，增强清晰度和张力。'}"
        )
        user = (
            "revise_chapter 润色并修订以下章节。\n"
            f"用户修改要求: {revision_instruction or '根据审查报告修复现有问题。'}\n"
            f"审查报告: {json.dumps(review_report.model_dump(), ensure_ascii=False)}\n"
            f"原文: {chapter_content}\n"
            "只输出修订后全文。"
        )
        return self._chat(system, user).strip()

    def polish_prose(self, content: str, instructions: str) -> str:
        """根据指令润色小说文笔：优化场景质感、对话自然度与句式节奏。"""
        system = (
            "你是严厉但克制的小说文笔润色编辑。你的任务是把草稿改成可读性更强的连载正文。"
            "必须保留核心剧情、人物行为、设定和因果，不新增大幅支线。"
            "重点改进：场景质感、动作细节、心理层次、对话自然度、句式节奏和结尾余味。"
            "删除提纲腔、总结腔、空泛热血、重复表达。只输出润色后的完整正文。"
        )
        user = (
            "prose_polish\n"
            f"润色指令: {instructions}\n"
            f"草稿正文:\n{content}\n"
            "只输出润色后的小说正文。"
        )
        return self._chat(system, user).strip()

    def revise_from_quality_report(
        self,
        chapter_content: str,
        quality_report: QualityReviewReport,
        style_guide: str = "",
    ) -> str:
        """根据质量评分卡逐项修复问题后输出修订全文。"""
        has_continuity = any(
            issue.dimension.startswith("continuity:") for issue in quality_report.issues
        )
        if has_continuity:
            return self._revise_with_continuity(chapter_content, quality_report, style_guide)

        system = (
            "你是负责闭环修复的小说编辑。根据质量评分卡逐项修复问题，输出完整修订后正文。"
            "要求：保留原剧情核心，补足逻辑、人设、伏笔、节奏和文风问题。"
            "对每个标注了 paragraph_range 的问题，定位到对应段落做精准修改，不要全文重写。"
            f"文风指南: {style_guide or '保持连贯、清晰、有叙事张力。'}"
        )
        user = (
            "revise_chapter_quality 修订以下章节。\n"
            f"质量评分卡: {json.dumps(quality_report.model_dump(), ensure_ascii=False)}\n"
            f"原文: {chapter_content}\n"
            "只输出修订后全文。"
        )
        return self._chat(system, user).strip()

    def _revise_with_continuity(
        self,
        chapter_content: str,
        quality_report: QualityReviewReport,
        style_guide: str = "",
    ) -> str:
        """同时处理写作质量和连续性问题的修订。

        将问题分为两类并给出不同修复策略：
        - 写作质量问题：局部修改，改进句式、节奏、描写
        - 连续性问题：检查事实矛盾，必要时添加过渡段落
        """
        quality_issues = [
            issue for issue in quality_report.issues
            if not issue.dimension.startswith("continuity:")
        ]
        continuity_issues = [
            issue for issue in quality_report.issues
            if issue.dimension.startswith("continuity:")
        ]

        quality_text = "\n".join(
            f"- [{issue.severity}] {issue.dimension}: {issue.description}"
            + (f" (定位: {issue.paragraph_range})" if issue.paragraph_range else "")
            + (f" 证据: {issue.evidence}" if issue.evidence else "")
            for issue in quality_issues
        ) if quality_issues else "无写作质量问题。"

        continuity_text = "\n".join(
            f"- [{issue.severity}] {issue.dimension}: {issue.description}"
            + (f" 证据: {issue.evidence}" if issue.evidence else "")
            for issue in continuity_issues
        ) if continuity_issues else "无连续性问题。"

        system = (
            "你是负责闭环修复的小说编辑。本次修订有两类问题需要处理：\n\n"
            "1. 写作质量问题（句式、节奏、描写、对话）：局部修改，保留原有剧情走向。\n"
            "2. 长篇连续性问题（人设漂移、位置跳变、伏笔矛盾）：这是跨章节的事实矛盾，\n"
            "   修复方式是在相关位置添加过渡说明或修正矛盾描写，而非删除冲突的剧情。\n\n"
            "修复原则：\n"
            "- 连续性问题优先——先解决事实矛盾，再处理文笔\n"
            "- 对标注了段落位置的问题，精准修改对应段落\n"
            "- 需要添加过渡时，用 1-3 句交代角色状态或场景变化\n"
            "- 保留所有未被标记为问题的原文内容\n"
            f"文风指南: {style_guide or '保持连贯、清晰、有叙事张力。'}"
        )
        user = (
            "revise_chapter_quality 修订以下章节（含连续性修复）。\n"
            f"=== 写作质量问题 ===\n{quality_text}\n\n"
            f"=== 长篇连续性问题 ===\n{continuity_text}\n\n"
            f"原文: {chapter_content}\n"
            "只输出修订后全文。"
        )
        return self._chat(system, user).strip()
