"""Hierarchical rolling summaries for long novels."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from novelforge.core.models import ChapterSummary, Story, VolumeSummary
from novelforge.llm.base import LLMClient


class ISummaryManager(ABC):
    @abstractmethod
    def generate_chapter_summary(self, story: Story, chapter_index: int, content: str) -> ChapterSummary:
        raise NotImplementedError

    @abstractmethod
    def get_rolling_context(self, story: Story, current_chapter: int, window: int = 3) -> str:
        raise NotImplementedError


class SummaryManager(ISummaryManager):
    def __init__(self, llm: LLMClient | None = None, chapters_per_volume: int = 10) -> None:
        self.llm = llm
        self.chapters_per_volume = chapters_per_volume

    def generate_chapter_summary(self, story: Story, chapter_index: int, content: str) -> ChapterSummary:
        summary = self._llm_summary(chapter_index, content) if self.llm else None
        if summary is None:
            summary = self._rule_summary(chapter_index, content)
        story.chapter_summaries[chapter_index] = summary
        return summary

    def generate_volume_summary(self, story: Story, volume: int, chapter_indices: list[int] | None = None) -> VolumeSummary:
        if chapter_indices is None:
            start = (volume - 1) * self.chapters_per_volume + 1
            end = volume * self.chapters_per_volume
            chapter_indices = list(range(start, end + 1))
        available = [story.chapter_summaries[index] for index in chapter_indices if index in story.chapter_summaries]
        if available:
            text = " ".join(item.chapter_summary for item in available)
            summary_text = self._compress(text, 500)
            chapter_range = (min(item.chapter_index for item in available), max(item.chapter_index for item in available))
        else:
            summary_text = ""
            chapter_range = (chapter_indices[0], chapter_indices[-1]) if chapter_indices else (1, 1)
        volume_summary = VolumeSummary(volume=volume, chapter_range=chapter_range, summary=summary_text)
        story.volume_summaries = [item for item in story.volume_summaries if item.volume != volume]
        story.volume_summaries.append(volume_summary)
        story.volume_summaries.sort(key=lambda item: item.volume)
        return volume_summary

    def get_rolling_context(self, story: Story, current_chapter: int, window: int = 3) -> str:
        previous = [
            story.chapter_summaries[index]
            for index in range(max(1, current_chapter - window), current_chapter)
            if index in story.chapter_summaries
        ]
        volume = max(1, (current_chapter - 1) // self.chapters_per_volume + 1)
        volume_summary = next((item for item in story.volume_summaries if item.volume == volume), None)
        all_book = self._compress(" ".join(item.summary for item in story.volume_summaries), 700)
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
        prompt = (
            "chapter_summary_generate: 为章节生成分层摘要。严格输出 JSON 对象，"
            "字段: chapter_index, scene_summaries, chapter_summary, key_events。\n"
            f"chapter={chapter_index}\ncontent={content[:10000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(self._extract_json(raw))
            return ChapterSummary.model_validate(data)
        except Exception:
            return None

    def _rule_summary(self, chapter_index: int, content: str) -> ChapterSummary:
        parts = [part.strip() for part in re.split(r"\n\s*\n|[。！？]", content) if part.strip()]
        scenes = [self._compress(part, 80) for part in parts[:6]]
        chapter_summary = self._compress("。".join(parts[:8]) or content, 300)
        return ChapterSummary(chapter_index=chapter_index, scene_summaries=scenes, chapter_summary=chapter_summary)

    def _compress(self, text: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def _extract_json(self, text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
