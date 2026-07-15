"""Causal event graph for long-form continuity."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from uuid import uuid4

from novelforge.core.utils import extract_json
from novelforge.domain import Story, TimelineEvent
from novelforge.llm.base import LLMClient


class ICausalityTracker(ABC):
    """因果事件跟踪器的抽象接口。"""

    @abstractmethod
    def add_event(self, story: Story, event: TimelineEvent) -> TimelineEvent:
        """向故事中添加一个因果事件并建立因果边，返回注册后的事件。"""
        raise NotImplementedError

    @abstractmethod
    def check_conflicts(self, story: Story, new_event: TimelineEvent) -> list[str]:
        """检查新事件是否与已有事件冲突（如前因缺失、时间倒置、因果循环），返回问题列表。"""
        raise NotImplementedError


class CausalityTracker(ICausalityTracker):
    """因果事件跟踪器，维护事件因果图，支持 LLM 抽取和规则回退。"""

    def __init__(self, llm: LLMClient | None = None) -> None:
        """初始化因果跟踪器。

        Args:
            llm: 可选的 LLM 客户端，为 None 时使用规则回退。
        """
        self.llm = llm

    def add_event(self, story: Story, event: TimelineEvent) -> TimelineEvent:
        """注册因果事件并自动为相关事件建立 causes/effects 双向引用边。"""
        if not event.id:
            event.id = f"ev-{uuid4().hex[:8]}"
        existing_ids = {item.id for item in story.knowledge.timeline}
        if event.id not in existing_ids:
            story.knowledge.timeline.append(event)
        for cause_id in event.causes:
            for cause in story.knowledge.timeline:
                if cause.id == cause_id and event.id not in cause.effects:
                    cause.effects.append(event.id)
        return event

    def check_conflicts(self, story: Story, new_event: TimelineEvent) -> list[str]:
        """检查新事件的前因是否存在、时间顺序是否合理、是否会引入因果循环。"""
        issues: list[str] = []
        by_id = {event.id: event for event in story.knowledge.timeline}
        for cause_id in new_event.causes:
            cause = by_id.get(cause_id)
            if cause is None:
                issues.append(f"事件 {new_event.id} 引用了不存在的前因 {cause_id}。")
            elif cause.chapter > new_event.chapter:
                issues.append(f"事件 {new_event.id} 的前因 {cause_id} 发生在未来章节。")
        if self._has_cycle(story, new_event):
            issues.append(f"事件 {new_event.id} 会造成因果循环。")
        return issues

    def extract_events_from_chapter(
        self, story: Story, chapter_index: int, content: str
    ) -> list[TimelineEvent]:
        """从章节中提取因果事件，先清除该章节旧事件，再用 LLM 或规则补充。"""
        story.knowledge.timeline = [
            event for event in story.knowledge.timeline if event.chapter != chapter_index
        ]
        events = self._llm_extract(chapter_index, content) if self.llm else []
        if not events:
            events = self._rule_extract(chapter_index, content)
        added: list[TimelineEvent] = []
        for event in events:
            if not self.check_conflicts(story, event):
                added.append(self.add_event(story, event))
        return added

    def get_related_chain(
        self, story: Story, event_id: str, depth: int = 2
    ) -> dict[str, list[dict]]:
        """BFS 搜索指定事件的因果链，返回 depth 层内所有关联事件。"""
        by_id = {event.id: event for event in story.knowledge.timeline}
        if event_id not in by_id:
            return {"events": []}
        seen = {event_id}
        queue = deque([(event_id, 0)])
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            event = by_id[current]
            related = event.causes + event.effects
            for next_id in related:
                if next_id in by_id and next_id not in seen:
                    seen.add(next_id)
                    queue.append((next_id, current_depth + 1))
        return {"events": [by_id[event_id].model_dump() for event_id in seen]}

    def _llm_extract(self, chapter_index: int, content: str) -> list[TimelineEvent]:
        """调用 LLM 从章节中提取因果事件，返回 TimelineEvent 列表。"""
        prompt = (
            "causal_event_extract: 从章节中抽取关键因果事件。严格输出 JSON 数组，"
            "字段: id, chapter, description, causes, effects。\n"
            f"chapter={chapter_index}\ncontent={content[:8000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(extract_json(raw))
            return [TimelineEvent.model_validate(item) for item in data if item.get("description")]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Rule-based extraction — genre-agnostic causal keywords
    # ------------------------------------------------------------------

    # Universal narrative turning-point words: decision, discovery, loss, gain,
    # betrayal, injury, departure, conflict.  These work across all genres.
    _CAUSAL_KEYWORDS: tuple[str, ...] = (
        "决定",
        "发现",
        "失去",
        "得到",
        "击败",
        "背叛",
        "真相",
        "受伤",
        "离开",
        "decide",
        "discover",
        "lose",
        "gain",
        "betray",
        "injure",
        "leave",
        "选择",
        "放弃",
        "获得",
        "觉醒",
        "突破",
        "失败",
        "成功",
        "牺牲",
        "拯救",
    )

    def _rule_extract(self, chapter_index: int, content: str) -> list[TimelineEvent]:
        """不依赖 LLM 的规则抽取：匹配通用因果关键词，最多提取 5 条。"""
        sentences = re.split(r"[。！？\n]+", content)
        events: list[TimelineEvent] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            if any(keyword in sentence for keyword in self._CAUSAL_KEYWORDS):
                events.append(
                    TimelineEvent(
                        id=f"ev-{chapter_index}-{len(events) + 1}",
                        chapter=chapter_index,
                        description=sentence[:120],
                    )
                )
            if len(events) >= 5:
                break
        if not events and content.strip():
            events.append(
                TimelineEvent(
                    id=f"ev-{chapter_index}-1", chapter=chapter_index, description=content[:120]
                )
            )
        return events

    def _has_cycle(self, story: Story, new_event: TimelineEvent) -> bool:
        """用 DFS 三色标记法检测添加 new_event 后是否会形成因果循环。"""
        edges = defaultdict(list)
        for event in story.knowledge.timeline + [new_event]:
            for cause_id in event.causes:
                edges[cause_id].append(event.id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for child in edges[node]:
                if visit(child):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in list(edges))
