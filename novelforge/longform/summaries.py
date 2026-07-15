"""Hierarchical rolling summaries for long novels."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from novelforge.core.utils import compress, extract_json
from novelforge.domain import ChapterSummary, Story, VolumeSummary
from novelforge.llm.base import LLMClient


class ISummaryManager(ABC):
    """摘要管理器的抽象接口。"""

    @abstractmethod
    def generate_chapter_summary(
        self, story: Story, chapter_index: int, content: str
    ) -> ChapterSummary:
        """根据章节内容生成 ChapterSummary，返回包含场景摘要和整体摘要的结构。"""
        raise NotImplementedError

    @abstractmethod
    def get_rolling_context(self, story: Story, current_chapter: int, window: int = 3) -> str:
        """获取当前章节的滚动上下文文本，包含附近章节摘要和卷概要。"""
        raise NotImplementedError


class SummaryManager(ISummaryManager):
    """分层摘要管理器，支持 LLM 提取和规则回退两种方式。"""

    def __init__(self, llm: LLMClient | None = None, chapters_per_volume: int = 10) -> None:
        """初始化摘要管理器。

        Args:
            llm: 可选的 LLM 客户端，为 None 时使用规则回退。
            chapters_per_volume: 每卷包含的章节数，默认 10。
        """
        self.llm = llm
        self.chapters_per_volume = chapters_per_volume

    def generate_chapter_summary(
        self, story: Story, chapter_index: int, content: str
    ) -> ChapterSummary:
        """生成单章摘要并存入 story.knowledge.chapter_summaries，优先使用 LLM，失败则回退到规则方法。"""
        summary = self._llm_summary(chapter_index, content) if self.llm else None
        if summary is None:
            summary = self._rule_summary(chapter_index, content)
        story.knowledge.chapter_summaries[chapter_index] = summary
        return summary

    def generate_volume_summary(
        self, story: Story, volume: int, chapter_indices: list[int] | None = None
    ) -> VolumeSummary:
        """聚合该卷内所有章节摘要，生成 VolumeSummary 并写入 story。"""
        if chapter_indices is None:
            start = (volume - 1) * self.chapters_per_volume + 1
            end = volume * self.chapters_per_volume
            chapter_indices = list(range(start, end + 1))
        available = [
            story.knowledge.chapter_summaries[index]
            for index in chapter_indices
            if index in story.knowledge.chapter_summaries
        ]
        if available:
            text = " ".join(item.chapter_summary for item in available)
            summary_text = compress(text, 500)
            chapter_range = (
                min(item.chapter_index for item in available),
                max(item.chapter_index for item in available),
            )
        else:
            summary_text = ""
            chapter_range = (chapter_indices[0], chapter_indices[-1]) if chapter_indices else (1, 1)
        volume_summary = VolumeSummary(
            volume=volume, chapter_range=chapter_range, summary=summary_text
        )
        story.knowledge.volume_summaries = [
            item for item in story.knowledge.volume_summaries if item.volume != volume
        ]
        story.knowledge.volume_summaries.append(volume_summary)
        story.knowledge.volume_summaries.sort(key=lambda item: item.volume)
        return volume_summary

    def get_rolling_context(self, story: Story, current_chapter: int, window: int = 3) -> str:
        """返回最近 window 章的滚动上下文，含最近章节摘要、当前卷概要和全书主线概要。"""
        previous = [
            story.knowledge.chapter_summaries[index]
            for index in range(max(1, current_chapter - window), current_chapter)
            if index in story.knowledge.chapter_summaries
        ]
        volume = max(1, (current_chapter - 1) // self.chapters_per_volume + 1)
        volume_summary = next(
            (item for item in story.knowledge.volume_summaries if item.volume == volume), None
        )
        all_book = compress(
            " ".join(item.summary for item in story.knowledge.volume_summaries), 700
        )
        lines = ["长篇滚动记忆:"]
        if previous:
            lines.append("最近章节摘要:")
            lines.extend(f"- 第{item.chapter_index}章: {item.chapter_summary}" for item in previous)
        if volume_summary:
            lines.append(f"当前卷概览: {volume_summary.summary}")
        if all_book:
            lines.append(f"全书主线概要: {all_book}")
        return "\n".join(lines)

    def _llm_summary(self, chapter_index: int, content: str) -> ChapterSummary | None:
        """调用 LLM 生成章节分层摘要，失败时返回 None 以触发规则回退。"""
        prompt = (
            "chapter_summary_generate: 为章节生成分层摘要。严格输出 JSON 对象，"
            "字段: chapter_index, scene_summaries, chapter_summary, key_events。\n"
            f"chapter={chapter_index}\ncontent={content[:10000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(extract_json(raw))
            return ChapterSummary.model_validate(data)
        except Exception:
            return None

    def _rule_summary(self, chapter_index: int, content: str) -> ChapterSummary:
        """不依赖 LLM 的规则摘要：按句号/空行切分内容，取前几句拼成摘要。"""
        parts = [part.strip() for part in re.split(r"\n\s*\n|[。！？]", content) if part.strip()]
        scenes = [compress(part, 80) for part in parts[:6]]
        chapter_summary = compress("。".join(parts[:8]) or content, 300)
        return ChapterSummary(
            chapter_index=chapter_index, scene_summaries=scenes, chapter_summary=chapter_summary
        )
