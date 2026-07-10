"""Second-generation long-novel memory orchestration.

This layer turns extracted continuity signals into durable, retrievable memory.
It is intentionally deterministic so it can run in tests and in API-key-free demos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from novelforge.core.models import (
    ArcSummary,
    CausalEvent,
    CharacterState,
    ChapterSummary,
    Foreshadowing,
    MemoryCard,
    Story,
)
from novelforge.core.utils import compress, dedupe
from novelforge.longform.ranker import MemoryRanker

if TYPE_CHECKING:
    from novelforge.core.config import MemoryRankerConfig


@dataclass
class ChapterContextPack:
    """构建章节上下文时传递给写作引擎的完整信息包。

    包含故事圣经、当前弧/卷、近期摘要、角色状态、待回收伏笔、因果线索、记忆卡片和连续性约束。
    """
    chapter_index: int
    story_bible: str = ""
    current_arc: str = ""
    current_volume: str = ""
    recent_summaries: list[str] = field(default_factory=list)
    character_states: list[str] = field(default_factory=list)
    pending_foreshadowings: list[str] = field(default_factory=list)
    causal_threads: list[str] = field(default_factory=list)
    retrieved_cards: list[str] = field(default_factory=list)
    continuity_constraints: list[str] = field(default_factory=list)


class MemoryEngineV2:
    """Maintain hierarchical memory for very long fiction projects."""

    def __init__(self, chapters_per_arc: int = 20, max_cards: int = 5000, memory_ranker_config: "MemoryRankerConfig | None" = None) -> None:
        """初始化记忆引擎。

        Args:
            chapters_per_arc: 每个故事弧包含的章节数，默认 20。
            max_cards: 记忆卡片最大数量，超出后按重要性裁剪，默认 5000。
            memory_ranker_config: MemoryRanker 配置，为 None 时使用默认权重。
        """
        self.chapters_per_arc = chapters_per_arc
        self.max_cards = max_cards
        self.ranker = MemoryRanker(memory_ranker_config)

    def process_chapter(
        self,
        story: Story,
        chapter_index: int,
        summary: ChapterSummary,
        events: list[CausalEvent],
        foreshadowings: list[Foreshadowing],
        character_states: list[CharacterState],
    ) -> dict[str, Any]:
        """处理一个章节的完整记忆管线。

        依次执行：卡片写入 → 弧摘要更新 → 故事圣经更新 → 卡片裁剪。
        返回包含 cards、arc_summary 和 story_bible 的字典。
        """
        cards = self._upsert_chapter_cards(story, chapter_index, summary, events, foreshadowings, character_states)
        arc = self.update_arc_summary(story, chapter_index)
        self.update_story_bible(story, chapter_index)
        self._trim_cards(story)
        return {"memory_cards": cards, "arc_summary": arc, "story_bible": story.story_bible}

    def build_context_pack(self, story: Story, chapter_index: int, query: str = "") -> ChapterContextPack:
        """组装章节上下文包，聚合故事圣经、弧信息、卷信息、近期摘要、角色状态、伏笔、因果和检索卡片。"""
        pack = ChapterContextPack(chapter_index=chapter_index)
        bible = story.story_bible
        if bible.core_premise or story.premise:
            pack.story_bible = "\n".join(
                line
                for line in [
                    f"Premise: {bible.core_premise or story.premise}",
                    f"Direction: {bible.current_direction}",
                    f"Style: {bible.style_guide or story.style_guide}",
                    "Active threads: " + "; ".join(bible.active_threads[:12]) if bible.active_threads else "",
                    "World rules: " + "; ".join(bible.world_rules[:8]) if bible.world_rules else "",
                ]
                if line
            )

        arc_index = self._arc_index(chapter_index)
        arc = next((item for item in story.arc_summaries if item.arc == arc_index), None)
        if arc:
            pack.current_arc = f"Arc {arc.arc} ch{arc.chapter_range[0]}-{arc.chapter_range[1]}: {arc.summary}"

        volume = max(1, (chapter_index - 1) // 10 + 1)
        volume_summary = next((item for item in story.volume_summaries if item.volume == volume), None)
        if volume_summary:
            pack.current_volume = f"Volume {volume_summary.volume} ch{volume_summary.chapter_range[0]}-{volume_summary.chapter_range[1]}: {volume_summary.summary}"

        recent = [
            story.chapter_summaries[index]
            for index in range(max(1, chapter_index - 5), chapter_index)
            if index in story.chapter_summaries
        ]
        pack.recent_summaries = [f"ch{item.chapter_index}: {item.chapter_summary}" for item in recent]

        involved = self._query_entities(story, chapter_index, query)
        pack.character_states = self._format_character_states(story, involved)
        pack.pending_foreshadowings = self._format_pending_foreshadowings(story, chapter_index, involved)
        pack.causal_threads = [
            f"{event.id}@ch{event.chapter}: {event.description}"
            for event in sorted(story.causal_events, key=lambda item: item.chapter)[-12:]
        ]
        pack.retrieved_cards = [self._format_card(card) for card in self.retrieve_cards(story, chapter_index, query, involved)]
        pack.continuity_constraints = list(bible.continuity_constraints[:12])
        return pack

    def format_context_pack(self, pack: ChapterContextPack, max_chars: int = 9000) -> str:
        """将 ChapterContextPack 格式化为分节的可读文本，总长度限制在 max_chars 以内。"""
        sections: list[str] = ["Memory Engine v2 Context Pack"]
        if pack.story_bible:
            sections.append("[Story Bible]\n" + pack.story_bible)
        if pack.current_arc:
            sections.append("[Current Arc]\n" + pack.current_arc)
        if pack.current_volume:
            sections.append("[Current Volume]\n" + pack.current_volume)
        if pack.recent_summaries:
            sections.append("[Recent Chapters]\n" + "\n".join("- " + item for item in pack.recent_summaries))
        if pack.character_states:
            sections.append("[Character States]\n" + "\n".join("- " + item for item in pack.character_states))
        if pack.pending_foreshadowings:
            sections.append("[Open Foreshadowing]\n" + "\n".join("- " + item for item in pack.pending_foreshadowings))
        if pack.causal_threads:
            sections.append("[Causal Threads]\n" + "\n".join("- " + item for item in pack.causal_threads))
        if pack.retrieved_cards:
            sections.append("[Retrieved Memory Cards]\n" + "\n".join("- " + item for item in pack.retrieved_cards))
        if pack.continuity_constraints:
            sections.append("[Continuity Constraints]\n" + "\n".join("- " + item for item in pack.continuity_constraints))
        return "\n\n".join(sections)[:max_chars]

    def retrieve_cards(
        self,
        story: Story,
        chapter_index: int,
        query: str = "",
        entities: set[str] | None = None,
        limit: int = 12,
    ) -> list[MemoryCard]:
        """通过 MemoryRanker 对 memory_cards 排序后返回 top-limit 条卡片。"""
        ranked = self.ranker.rank_cards(story.memory_cards, query, chapter_index, entities=entities, limit=limit)
        return [item.item for item in ranked]

    def update_arc_summary(self, story: Story, chapter_index: int) -> ArcSummary:
        """更新当前章节所属故事弧的摘要。

        聚合该弧内章节摘要和因果事件，压缩后写入 story.arc_summaries 并返回 ArcSummary。
        """
        arc_index = self._arc_index(chapter_index)
        start = (arc_index - 1) * self.chapters_per_arc + 1
        end = arc_index * self.chapters_per_arc
        summaries = [story.chapter_summaries[index] for index in range(start, end + 1) if index in story.chapter_summaries]
        text = " ".join(item.chapter_summary for item in summaries)
        events = [
            event.description
            for event in story.causal_events
            if start <= event.chapter <= end
        ][-8:]
        pending = [
            item.description
            for item in story.foreshadowings
            if item.status == "pending" and start <= item.created_chapter <= end
        ][-8:]
        summary = compress(" ".join([text] + events), 900)
        arc = ArcSummary(
            arc=arc_index,
            chapter_range=(start, max(start, min(end, chapter_index))),
            summary=summary,
            key_threads=events,
            open_questions=pending,
        )
        story.arc_summaries = [item for item in story.arc_summaries if item.arc != arc_index]
        story.arc_summaries.append(arc)
        story.arc_summaries.sort(key=lambda item: item.arc)
        return arc

    def update_story_bible(self, story: Story, chapter_index: int) -> None:
        """更新故事圣经。

        刷新核心前提、风格、当前方向、活跃线索、角色名册和连续性约束。
        """
        bible = story.story_bible
        bible.core_premise = story.premise
        bible.style_guide = story.style_guide
        latest_arc = max(story.arc_summaries, key=lambda item: item.arc, default=None)
        latest_summary = story.chapter_summaries.get(chapter_index)
        bible.current_direction = compress(
            latest_summary.chapter_summary if latest_summary else (latest_arc.summary if latest_arc else story.premise),
            600,
        )
        bible.active_threads = dedupe(
            [item.description for item in story.foreshadowings if item.status == "pending"][-20:]
            + [event.description for event in sorted(story.causal_events, key=lambda item: item.chapter)[-12:]]
        )[:24]
        bible.character_roster = {}
        for character_id, character in story.characters.items():
            current = max(story.character_states.get(character_id, []), key=lambda item: item.chapter, default=None)
            state = ""
            if current:
                state = f"ch{current.chapter}: {current.emotional_state}; {current.location}"
            bible.character_roster[character_id] = compress(f"{character.name} {state}".strip(), 240)
        bible.continuity_constraints = dedupe(
            bible.continuity_constraints
            + [f"Keep foreshadowing open until resolved: {item.id} {item.description}" for item in story.foreshadowings if item.status == "pending"][-20:]
            + [f"Respect latest state of {cid}: {states[-1].emotional_state}, {states[-1].location}" for cid, states in story.character_states.items() if states]
        )[:30]
        bible.updated_at = datetime.now(timezone.utc)

    def _upsert_chapter_cards(
        self,
        story: Story,
        chapter_index: int,
        summary: ChapterSummary,
        events: list[CausalEvent],
        foreshadowings: list[Foreshadowing],
        character_states: list[CharacterState],
    ) -> list[MemoryCard]:
        """将章节摘要、因果事件、伏笔和角色状态转换为 MemoryCard 并合并到 story 中。

        保留其他章节的卡片，覆盖当前章节的卡片，返回本次创建的卡片列表。
        """
        cards: list[MemoryCard] = [
            MemoryCard(
                id=f"{story.id}:ch:{chapter_index}:summary",
                type="chapter_summary",
                content=summary.chapter_summary,
                chapter=chapter_index,
                importance=7,
                tags=["summary"],
            )
        ]
        for event in events:
            cards.append(
                MemoryCard(
                    id=f"{story.id}:event:{event.id}",
                    type="causal_event",
                    content=event.description,
                    chapter=event.chapter,
                    importance=8,
                    tags=["causal_event"],
                )
            )
        for item in foreshadowings:
            cards.append(
                MemoryCard(
                    id=f"{story.id}:foreshadowing:{item.id}",
                    type="foreshadowing",
                    content=item.description,
                    chapter=item.created_chapter,
                    importance=9,
                    tags=["foreshadowing", item.status],
                    last_seen_chapter=chapter_index,
                )
            )
        for state in character_states:
            cards.append(
                MemoryCard(
                    id=f"{story.id}:character_state:{state.character_id}:ch:{chapter_index}",
                    type="character_state",
                    content=self._format_state(state),
                    chapter=chapter_index,
                    importance=8,
                    entities=[state.character_id],
                    tags=["character_state"],
                )
            )
        existing = {card.id: card for card in story.memory_cards if card.chapter != chapter_index}
        for card in cards:
            existing[card.id] = card
        story.memory_cards = sorted(existing.values(), key=lambda item: (item.chapter, item.importance))
        return cards

    def _trim_cards(self, story: Story) -> None:
        """当卡片数超过 max_cards 时按重要性+章节排序后裁剪。"""
        if len(story.memory_cards) <= self.max_cards:
            return
        story.memory_cards = sorted(story.memory_cards, key=lambda item: (item.importance, item.chapter), reverse=True)[: self.max_cards]
        story.memory_cards.sort(key=lambda item: (item.chapter, item.importance))

    def _query_entities(self, story: Story, chapter_index: int, query: str) -> set[str]:
        """从大纲和查询中推断相关角色实体集合。"""
        entities: set[str] = set()
        try:
            outline = story.get_outline(chapter_index)
            if outline.pov_character:
                entities.add(outline.pov_character)
            query += " " + " ".join([outline.title, outline.summary, outline.conflict, outline.pov_character or ""])
        except KeyError:
            pass
        for character_id, character in story.characters.items():
            if character_id in query or (character.name and character.name in query):
                entities.add(character_id)
        return entities

    def _format_character_states(self, story: Story, entities: set[str]) -> list[str]:
        """格式化指定实体（或全部角色）的当前状态为可读字符串列表。"""
        candidates = entities or set(story.characters.keys())
        rows: list[str] = []
        for character_id in sorted(candidates):
            current = max(story.character_states.get(character_id, []), key=lambda item: item.chapter, default=None)
            if current:
                name = story.characters.get(character_id).name if character_id in story.characters else character_id
                rows.append(f"{name}: {self._format_state(current)}")
        return rows[:12]

    def _format_pending_foreshadowings(self, story: Story, chapter_index: int, entities: set[str]) -> list[str]:
        """格式化未回收伏笔列表，按与当前章节的距离排序。"""
        pending = [item for item in story.foreshadowings if item.status == "pending"]
        pending.sort(key=lambda item: ((item.target_chapter or chapter_index + 999) - chapter_index, -item.created_chapter))
        return [
            f"{item.id} created@ch{item.created_chapter}"
            + (f" target@ch{item.target_chapter}" if item.target_chapter else "")
            + f": {item.description}"
            for item in pending[:12]
        ]

    def _format_card(self, card: MemoryCard) -> str:
        """格式化单张 MemoryCard 为可读字符串。"""
        entities = f" entities={','.join(card.entities)}" if card.entities else ""
        return f"{card.type}@ch{card.chapter}{entities}: {card.content}"

    def _format_state(self, state: CharacterState) -> str:
        """格式化单个 CharacterState 为压缩后的可读字符串。"""
        parts = [
            f"ch{state.chapter}",
            state.emotional_state,
            state.location,
            "; ".join(state.knowledge_gained[:3]),
        ]
        if state.relationship_changes:
            parts.append("relations=" + ", ".join(f"{k}:{v}" for k, v in list(state.relationship_changes.items())[:4]))
        return compress(" | ".join(part for part in parts if part), 320)


    def _arc_index(self, chapter_index: int) -> int:
        """根据章节编号计算所属的故事弧编号。"""
        return max(1, (chapter_index - 1) // self.chapters_per_arc + 1)
