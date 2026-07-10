"""Foreshadowing tracking for long-form fiction."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from uuid import uuid4

from novelforge.core.models import ChapterOutline, Foreshadowing, Story
from novelforge.core.utils import extract_json
from novelforge.llm.base import LLMClient


class IForeshadowingTracker(ABC):
    """伏笔跟踪器的抽象接口。"""

    @abstractmethod
    def register(self, story: Story, foreshadowing: Foreshadowing) -> Foreshadowing:
        """注册一条伏笔到故事中，返回注册后的 Foreshadowing。"""
        raise NotImplementedError

    @abstractmethod
    def get_pending(self, story: Story) -> list[Foreshadowing]:
        """获取所有状态为 pending 的未回收伏笔列表。"""
        raise NotImplementedError


class ForeshadowingTracker(IForeshadowingTracker):
    """伏笔跟踪器，支持 LLM 检测与规则回退，可自动回收匹配关键词的伏笔。"""

    def __init__(self, llm: LLMClient | None = None) -> None:
        """初始化伏笔跟踪器。

        Args:
            llm: 可选的 LLM 客户端，为 None 时使用规则回退。
        """
        self.llm = llm

    def register(self, story: Story, foreshadowing: Foreshadowing) -> Foreshadowing:
        """注册伏笔到 story.foreshadowings，若未指定 ID 则自动生成，去重后返回。"""
        if not foreshadowing.id:
            foreshadowing.id = f"fs-{uuid4().hex[:8]}"
        if not any(item.id == foreshadowing.id for item in story.foreshadowings):
            story.foreshadowings.append(foreshadowing)
        return foreshadowing

    def get_pending(self, story: Story) -> list[Foreshadowing]:
        """返回所有状态为 pending 的伏笔列表。"""
        return [item for item in story.foreshadowings if item.status == "pending"]

    def fulfill(self, story: Story, foreshadowing_id: str, chapter: int) -> Foreshadowing | None:
        """将指定伏笔标记为 fulfilled 并记录回收章节，返回更新后的伏笔，未找到返回 None。"""
        for item in story.foreshadowings:
            if item.id == foreshadowing_id:
                item.status = "fulfilled"
                item.notes = (item.notes + f"\n回收于第{chapter}章").strip()
                return item
        return None

    def suggest_placement(self, chapter_outline: ChapterOutline) -> str:
        """根据章节大纲，调用 LLM（或规则）给出伏笔埋设/回收的建议。"""
        if self.llm is None:
            return f"第{chapter_outline.chapter_index}章可围绕[{chapter_outline.conflict}]埋下代价或秘密类伏笔。"
        prompt = (
            "你是小说伏笔设计师。根据章节大纲判断适合埋下或回收伏笔的位置，给出简短建议。\n"
            f"章节大纲: {chapter_outline.model_dump_json()}"
        )
        return self.llm.chat_completion([{"role": "user", "content": prompt}]).strip()

    def analyze_new_chapter(self, story: Story, chapter_index: int, content: str) -> list[Foreshadowing]:
        """分析新章节：检测新伏笔、去重注册、自动回收已触发的伏笔。返回本次注册的伏笔列表。"""
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
        """调用 LLM 从章节中检测潜在伏笔，返回 Foreshadowing 列表。"""
        prompt = (
            "foreshadowing_extract: 从章节中识别可能的新伏笔。严格输出 JSON 数组，"
            "字段: id, description, created_chapter, target_chapter, status, notes。\n"
            f"chapter={chapter_index}\ncontent={content[:8000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(extract_json(raw))
            return [Foreshadowing.model_validate(item) for item in data if item.get("description")]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Rule-based detection — genre-agnostic signal groups
    # ------------------------------------------------------------------

    # Signal patterns that work across fantasy, sci-fi, romance, mystery,
    # historical, wuxia, and contemporary fiction.
    _FORESHADOW_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
        ("隐藏信息", ("秘密", "隐瞒", "隐情", "不能说", "藏", "瞒", "真相", "secret", "hide")),
        ("预兆/预言", ("预言", "征兆", "预感", "梦", "预兆", "prophecy", "omen", "dream")),
        ("特殊物品", ("钥匙", "信物", "纹章", "遗物", "戒指", "项链", "照片", "日记", "地图", "key", "artifact", "token")),
        ("未解之谜", ("奇怪", "不对劲", "似曾相识", "没有解释", "谜", "strange", "unexplained")),
        ("潜在威胁", ("威胁", "追杀", "盯上", "通缉", "埋伏", "暗处", "threat", "danger", "hunt")),
        ("未兑现承诺", ("承诺", "约定", "发誓", "誓言", "保证", "promise", "oath", "vow")),
    ]

    def _rule_detect(self, chapter_index: int, content: str) -> list[Foreshadowing]:
        """不依赖 LLM 的规则检测：用通用叙事信号词匹配常见伏笔类型。"""
        for category, markers in self._FORESHADOW_SIGNALS:
            if not any(marker in content for marker in markers):
                continue
            return [
                Foreshadowing(
                    id=f"fs-{chapter_index}-{abs(hash(category + content[:30])) % 10000}",
                    description=f"第{chapter_index}章出现[{category}]类线索，可能需要后续回收。",
                    created_chapter=chapter_index,
                )
            ]
        return []

    # Genre-agnostic fulfilment signal words — reveal, discovery, resolution.
    _FULFIL_SIGNALS: tuple[str, ...] = (
        "真相", "原来", "终于", "揭开", "回想", "揭露", "水落石出",
        "reveal", "discover", "realize", "uncover",
    )

    def _auto_fulfill(self, story: Story, chapter_index: int, content: str) -> None:
        """自动检查当前章节是否包含通用回收信号词，尝试回收匹配的 pending 伏笔。"""
        for item in self.get_pending(story):
            if item.created_chapter == chapter_index:
                continue
            keywords = [word for word in re.findall(r"[\w一-鿿]{2,}", item.description) if len(word) >= 2]
            if any(word in content for word in keywords[:3]) and any(token in content for token in self._FULFIL_SIGNALS):
                self.fulfill(story, item.id, chapter_index)

    def _is_duplicate(self, story: Story, candidate: Foreshadowing) -> bool:
        """判断候选伏笔是否与已有伏笔重复（同章节 + 同描述）。"""
        return any(
            item.created_chapter == candidate.created_chapter and item.description == candidate.description
            for item in story.foreshadowings
        )
