"""Causal event graph for long-form continuity."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from uuid import uuid4

from novelforge.core.models import CausalEvent, Story
from novelforge.llm.base import LLMClient


class ICausalityTracker(ABC):
    @abstractmethod
    def add_event(self, story: Story, event: CausalEvent) -> CausalEvent:
        raise NotImplementedError

    @abstractmethod
    def check_conflicts(self, story: Story, new_event: CausalEvent) -> list[str]:
        raise NotImplementedError


class CausalityTracker(ICausalityTracker):
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def add_event(self, story: Story, event: CausalEvent) -> CausalEvent:
        if not event.id:
            event.id = f"ev-{uuid4().hex[:8]}"
        existing_ids = {item.id for item in story.causal_events}
        if event.id not in existing_ids:
            story.causal_events.append(event)
        for cause_id in event.causes:
            for cause in story.causal_events:
                if cause.id == cause_id and event.id not in cause.effects:
                    cause.effects.append(event.id)
        return event

    def check_conflicts(self, story: Story, new_event: CausalEvent) -> list[str]:
        issues: list[str] = []
        by_id = {event.id: event for event in story.causal_events}
        for cause_id in new_event.causes:
            cause = by_id.get(cause_id)
            if cause is None:
                issues.append(f"事件 {new_event.id} 引用了不存在的前因 {cause_id}。")
            elif cause.chapter > new_event.chapter:
                issues.append(f"事件 {new_event.id} 的前因 {cause_id} 发生在未来章节。")
        if self._has_cycle(story, new_event):
            issues.append(f"事件 {new_event.id} 会造成因果循环。")
        return issues

    def extract_events_from_chapter(self, story: Story, chapter_index: int, content: str) -> list[CausalEvent]:
        story.causal_events = [event for event in story.causal_events if event.chapter != chapter_index]
        events = self._llm_extract(chapter_index, content) if self.llm else []
        if not events:
            events = self._rule_extract(chapter_index, content)
        added: list[CausalEvent] = []
        for event in events:
            if not self.check_conflicts(story, event):
                added.append(self.add_event(story, event))
        return added

    def get_related_chain(self, story: Story, event_id: str, depth: int = 2) -> dict[str, list[dict]]:
        by_id = {event.id: event for event in story.causal_events}
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

    def _llm_extract(self, chapter_index: int, content: str) -> list[CausalEvent]:
        prompt = (
            "causal_event_extract: 从章节中抽取关键因果事件。严格输出 JSON 数组，"
            "字段: id, chapter, description, causes, effects。\n"
            f"chapter={chapter_index}\ncontent={content[:8000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(self._extract_json(raw))
            return [CausalEvent.model_validate(item) for item in data if item.get("description")]
        except Exception:
            return []

    def _rule_extract(self, chapter_index: int, content: str) -> list[CausalEvent]:
        sentences = re.split(r"[。！？\n]+", content)
        keywords = ("决定", "发现", "失去", "得到", "击败", "背叛", "真相", "受伤", "离开")
        events: list[CausalEvent] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            if any(keyword in sentence for keyword in keywords):
                events.append(
                    CausalEvent(
                        id=f"ev-{chapter_index}-{len(events) + 1}",
                        chapter=chapter_index,
                        description=sentence[:120],
                    )
                )
            if len(events) >= 5:
                break
        if not events and content.strip():
            events.append(CausalEvent(id=f"ev-{chapter_index}-1", chapter=chapter_index, description=content[:120]))
        return events

    def _has_cycle(self, story: Story, new_event: CausalEvent) -> bool:
        edges = defaultdict(list)
        for event in story.causal_events + [new_event]:
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

    def _extract_json(self, text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
