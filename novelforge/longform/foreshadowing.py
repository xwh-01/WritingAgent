"""Foreshadowing tracking for long-form fiction."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from uuid import uuid4

from novelforge.core.models import ChapterOutline, Foreshadowing, Story
from novelforge.llm.base import LLMClient


class IForeshadowingTracker(ABC):
    @abstractmethod
    def register(self, story: Story, foreshadowing: Foreshadowing) -> Foreshadowing:
        raise NotImplementedError

    @abstractmethod
    def get_pending(self, story: Story) -> list[Foreshadowing]:
        raise NotImplementedError


class ForeshadowingTracker(IForeshadowingTracker):
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def register(self, story: Story, foreshadowing: Foreshadowing) -> Foreshadowing:
        if not foreshadowing.id:
            foreshadowing.id = f"fs-{uuid4().hex[:8]}"
        if not any(item.id == foreshadowing.id for item in story.foreshadowings):
            story.foreshadowings.append(foreshadowing)
        return foreshadowing

    def get_pending(self, story: Story) -> list[Foreshadowing]:
        return [item for item in story.foreshadowings if item.status == "pending"]

    def fulfill(self, story: Story, foreshadowing_id: str, chapter: int) -> Foreshadowing | None:
        for item in story.foreshadowings:
            if item.id == foreshadowing_id:
                item.status = "fulfilled"
                item.notes = (item.notes + f"\n回收于第{chapter}章").strip()
                return item
        return None

    def suggest_placement(self, chapter_outline: ChapterOutline) -> str:
        if self.llm is None:
            return f"第{chapter_outline.chapter_index}章可围绕“{chapter_outline.conflict}”埋下代价或秘密类伏笔。"
        prompt = (
            "你是小说伏笔设计师。根据章节大纲判断适合埋下或回收伏笔的位置，给出简短建议。\n"
            f"章节大纲: {chapter_outline.model_dump_json()}"
        )
        return self.llm.chat_completion([{"role": "user", "content": prompt}]).strip()

    def analyze_new_chapter(self, story: Story, chapter_index: int, content: str) -> list[Foreshadowing]:
        detected = self._llm_detect(chapter_index, content) if self.llm else []
        if not detected:
            detected = self._rule_detect(chapter_index, content)
        registered: list[Foreshadowing] = []
        for item in detected:
            if self._is_duplicate(story, item):
                continue
            registered.append(self.register(story, item))
        self._auto_fulfill(story, chapter_index, content)
        return registered

    def _llm_detect(self, chapter_index: int, content: str) -> list[Foreshadowing]:
        prompt = (
            "foreshadowing_extract: 从章节中识别可能的新伏笔。严格输出 JSON 数组，"
            "字段: id, description, created_chapter, target_chapter, status, notes。\n"
            f"chapter={chapter_index}\ncontent={content[:8000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(self._extract_json(raw))
            return [Foreshadowing.model_validate(item) for item in data if item.get("description")]
        except Exception:
            return []

    def _rule_detect(self, chapter_index: int, content: str) -> list[Foreshadowing]:
        markers = ("秘密", "预言", "钥匙", "梦", "纹章", "信物", "奇怪", "似曾相识", "没有解释")
        found: list[Foreshadowing] = []
        for marker in markers:
            if marker in content:
                found.append(
                    Foreshadowing(
                        id=f"fs-{chapter_index}-{abs(hash(marker + content[:30])) % 10000}",
                        description=f"第{chapter_index}章出现“{marker}”相关线索，可能需要后续回收。",
                        created_chapter=chapter_index,
                    )
                )
                break
        return found

    def _auto_fulfill(self, story: Story, chapter_index: int, content: str) -> None:
        for item in self.get_pending(story):
            if item.created_chapter == chapter_index:
                continue
            keywords = [word for word in re.findall(r"[\w\u4e00-\u9fff]{2,}", item.description) if len(word) >= 2]
            if any(word in content for word in keywords[:3]) and any(token in content for token in ("真相", "原来", "终于", "揭开", "回想")):
                self.fulfill(story, item.id, chapter_index)

    def _is_duplicate(self, story: Story, candidate: Foreshadowing) -> bool:
        return any(
            item.created_chapter == candidate.created_chapter and item.description == candidate.description
            for item in story.foreshadowings
        )

    def _extract_json(self, text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
