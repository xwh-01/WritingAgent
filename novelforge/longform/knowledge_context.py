"""Build durable knowledge summaries and bounded writing context.

This layer turns extracted continuity signals into durable, retrievable knowledge.
It is intentionally deterministic so it can run in tests and in API-key-free demos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from novelforge.core.utils import compress, dedupe
from novelforge.domain import (
    ArcSummary,
    ChapterSummary,
    CharacterState,
    Foreshadowing,
    RetrievalNote,
    Story,
    TimelineEvent,
)
from novelforge.longform.retrieval import RetrievalRanker

if TYPE_CHECKING:
    from novelforge.core.config import RetrievalConfig


@dataclass
class WritingContext:
    """构建章节上下文时传递给写作引擎的完整信息包。

    包含故事圣经、当前弧/卷、近期摘要、角色状态、待回收伏笔、因果线索、记忆卡片和连续性约束。
    """

    chapter_index: int
    guide: str = ""
    arc_summary: str = ""
    volume_summary: str = ""
    recent_chapters: list[str] = field(default_factory=list)
    character_states: list[str] = field(default_factory=list)
    pending_foreshadowings: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    retrieval_notes: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)


class KnowledgeContextEngine:
    """Maintain hierarchical knowledge for long-form fiction projects."""

    def __init__(
        self,
        chapters_per_arc: int = 20,
        max_notes: int = 5000,
        retrieval_config: "RetrievalConfig | None" = None,
    ) -> None:
        """初始化记忆引擎。

        Args:
            chapters_per_arc: 每个故事弧包含的章节数，默认 20。
            max_notes: 记忆卡片最大数量，超出后按重要性裁剪，默认 5000。
            retrieval_config: RetrievalRanker 配置，为 None 时使用默认权重。
        """
        self.chapters_per_arc = chapters_per_arc
        self.max_notes = max_notes
        self.ranker = RetrievalRanker(retrieval_config)

    def process_chapter(
        self,
        story: Story,
        chapter_index: int,
        summary: ChapterSummary,
        events: list[TimelineEvent],
        foreshadowings: list[Foreshadowing],
        character_states: list[CharacterState],
    ) -> dict[str, Any]:
        """处理一个章节的完整记忆管线。

        依次执行：卡片写入 → 弧摘要更新 → 故事圣经更新 → 卡片裁剪。
        返回包含 cards、arc_summary 和 guide 的字典。
        """
        notes = self._upsert_retrieval_notes(
            story, chapter_index, summary, events, foreshadowings, character_states
        )
        arc = self.update_arc_summary(story, chapter_index)
        self.update_guide(story, chapter_index)
        self._trim_retrieval_notes(story)
        return {"retrieval_notes": notes, "arc_summary": arc, "guide": story.knowledge.guide}

    def build_context_pack(
        self, story: Story, chapter_index: int, query: str = ""
    ) -> WritingContext:
        """组装章节上下文包，聚合故事圣经、弧信息、卷信息、近期摘要、角色状态、伏笔、因果和检索卡片。"""
        pack = WritingContext(chapter_index=chapter_index)
        bible = story.knowledge.guide
        if bible.core_premise or story.premise:
            pack.guide = "\n".join(
                line
                for line in [
                    f"Premise: {bible.core_premise or story.premise}",
                    f"Style: {bible.style_guide or story.style_guide}",
                    "World rules: " + "; ".join(bible.world_rules[:8]) if bible.world_rules else "",
                ]
                if line
            )

        arc_index = self._arc_index(chapter_index)
        arc = next((item for item in story.knowledge.arc_summaries if item.arc == arc_index), None)
        if arc and arc.chapter_range[1] < chapter_index:
            pack.arc_summary = (
                f"Arc {arc.arc} ch{arc.chapter_range[0]}-{arc.chapter_range[1]}: {arc.summary}"
            )

        volume = max(1, (chapter_index - 1) // 10 + 1)
        volume_summary = next(
            (item for item in story.knowledge.volume_summaries if item.volume == volume), None
        )
        if volume_summary and volume_summary.chapter_range[1] < chapter_index:
            pack.volume_summary = f"Volume {volume_summary.volume} ch{volume_summary.chapter_range[0]}-{volume_summary.chapter_range[1]}: {volume_summary.summary}"

        recent = [
            story.knowledge.chapter_summaries[index]
            for index in range(max(1, chapter_index - 5), chapter_index)
            if index in story.knowledge.chapter_summaries
        ]
        pack.recent_chapters = [
            f"ch{item.chapter_index}: {item.chapter_summary}" for item in recent
        ]

        involved = self._query_entities(story, chapter_index, query)
        pack.character_states = self._format_character_states(story, involved, chapter_index)
        pack.pending_foreshadowings = self._format_pending_foreshadowings(
            story, chapter_index, involved
        )
        pack.timeline = [
            f"{event.id}@ch{event.chapter}: {event.description}"
            for event in sorted(
                (item for item in story.knowledge.timeline if item.chapter < chapter_index),
                key=lambda item: item.chapter,
            )[-12:]
        ]
        pack.retrieval_notes = [
            self._format_note(card)
            for card in self.retrieve_notes(story, chapter_index, query, involved)
        ]
        pack.hard_constraints = list(bible.continuity_constraints[:12])
        return pack

    def format_context_pack(self, pack: WritingContext, max_chars: int = 9000) -> str:
        """将 WritingContext 格式化为分节的可读文本，总长度限制在 max_chars 以内。"""
        sections: list[str] = ["NovelForge Writing Context"]
        if pack.guide:
            sections.append("[Story Guide]\n" + pack.guide)
        if pack.arc_summary:
            sections.append("[Current Arc]\n" + pack.arc_summary)
        if pack.volume_summary:
            sections.append("[Current Volume]\n" + pack.volume_summary)
        if pack.recent_chapters:
            sections.append(
                "[Recent Chapters]\n" + "\n".join("- " + item for item in pack.recent_chapters)
            )
        if pack.character_states:
            sections.append(
                "[Character States]\n" + "\n".join("- " + item for item in pack.character_states)
            )
        if pack.pending_foreshadowings:
            sections.append(
                "[Open Foreshadowing]\n"
                + "\n".join("- " + item for item in pack.pending_foreshadowings)
            )
        if pack.timeline:
            sections.append("[Timeline]\n" + "\n".join("- " + item for item in pack.timeline))
        if pack.retrieval_notes:
            sections.append(
                "[Retrieved Knowledge]\n" + "\n".join("- " + item for item in pack.retrieval_notes)
            )
        if pack.hard_constraints:
            sections.append(
                "[Continuity Constraints]\n"
                + "\n".join("- " + item for item in pack.hard_constraints)
            )
        return "\n\n".join(sections)[:max_chars]

    def retrieve_notes(
        self,
        story: Story,
        chapter_index: int,
        query: str = "",
        entities: set[str] | None = None,
        limit: int = 12,
    ) -> list[RetrievalNote]:
        """Return the most relevant structured notes for the target chapter."""
        ranked = self.ranker.rank_notes(
            story.knowledge.retrieval_notes, query, chapter_index, entities=entities, limit=limit
        )
        return [item.item for item in ranked]

    def update_arc_summary(self, story: Story, chapter_index: int) -> ArcSummary:
        """更新当前章节所属故事弧的摘要。

        聚合该弧内章节摘要和因果事件，压缩后写入 story.knowledge.arc_summaries 并返回 ArcSummary。
        """
        arc_index = self._arc_index(chapter_index)
        start = (arc_index - 1) * self.chapters_per_arc + 1
        end = arc_index * self.chapters_per_arc
        summaries = [
            story.knowledge.chapter_summaries[index]
            for index in range(start, end + 1)
            if index in story.knowledge.chapter_summaries
        ]
        text = " ".join(item.chapter_summary for item in summaries)
        events = [
            event.description for event in story.knowledge.timeline if start <= event.chapter <= end
        ][-8:]
        pending = [
            item.description
            for item in story.knowledge.foreshadowings
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
        story.knowledge.arc_summaries = [
            item for item in story.knowledge.arc_summaries if item.arc != arc_index
        ]
        story.knowledge.arc_summaries.append(arc)
        story.knowledge.arc_summaries.sort(key=lambda item: item.arc)
        return arc

    def update_guide(self, story: Story, chapter_index: int) -> None:
        """更新故事圣经。

        刷新核心前提、风格、当前方向、活跃线索、角色名册和连续性约束。
        """
        bible = story.knowledge.guide
        bible.core_premise = story.premise
        bible.style_guide = story.style_guide
        latest_arc = max(story.knowledge.arc_summaries, key=lambda item: item.arc, default=None)
        latest_summary = story.knowledge.chapter_summaries.get(chapter_index)
        bible.current_direction = compress(
            (
                latest_summary.chapter_summary
                if latest_summary
                else (latest_arc.summary if latest_arc else story.premise)
            ),
            600,
        )
        bible.active_threads = dedupe(
            [
                item.description
                for item in story.knowledge.foreshadowings
                if item.status == "pending"
            ][-20:]
            + [
                event.description
                for event in sorted(story.knowledge.timeline, key=lambda item: item.chapter)[-12:]
            ]
        )[:24]
        bible.character_roster = {}
        for character_id, character in story.design.characters.items():
            current = max(
                story.knowledge.character_states.get(character_id, []),
                key=lambda item: item.chapter,
                default=None,
            )
            state = ""
            if current:
                state = f"ch{current.chapter}: {current.emotional_state}; {current.location}"
            bible.character_roster[character_id] = compress(
                f"{character.name} {state}".strip(), 240
            )
        for observation in story.knowledge.character_observations:
            if observation.character_id not in bible.character_roster:
                bible.character_roster[observation.character_id] = compress(
                    observation.name,
                    240,
                )
        bible.world_rules = dedupe(
            [setting.content for setting in story.design.world_settings]
            + [fact.content for fact in story.knowledge.world_facts]
        )[:30]
        bible.continuity_constraints = dedupe(
            [
                constraint
                for chapter_constraints in story.knowledge.chapter_constraints.values()
                for constraint in chapter_constraints
            ]
            + [
                f"Keep foreshadowing open until resolved: {item.id} {item.description}"
                for item in story.knowledge.foreshadowings
                if item.status == "pending"
            ][-20:]
            + [
                f"Respect latest state of {cid}: {states[-1].emotional_state}, {states[-1].location}"
                for cid, states in story.knowledge.character_states.items()
                if states
            ]
        )[:30]
        bible.updated_at = datetime.now(timezone.utc)

    def _upsert_retrieval_notes(
        self,
        story: Story,
        chapter_index: int,
        summary: ChapterSummary,
        events: list[TimelineEvent],
        foreshadowings: list[Foreshadowing],
        character_states: list[CharacterState],
    ) -> list[RetrievalNote]:
        """将章节摘要、因果事件、伏笔和角色状态转换为 RetrievalNote 并合并到 story 中。

        保留其他章节的卡片，覆盖当前章节的卡片，返回本次创建的卡片列表。
        """
        notes: list[RetrievalNote] = [
            RetrievalNote(
                id=f"{story.id}:ch:{chapter_index}:summary",
                type="chapter_summary",
                content=summary.chapter_summary,
                chapter=chapter_index,
                importance=7,
                tags=["summary"],
            )
        ]
        for event in events:
            notes.append(
                RetrievalNote(
                    id=f"{story.id}:event:{event.id}",
                    type="timeline_event",
                    content=event.description,
                    chapter=event.chapter,
                    importance=8,
                    tags=["timeline_event"],
                )
            )
        for item in foreshadowings:
            notes.append(
                RetrievalNote(
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
            notes.append(
                RetrievalNote(
                    id=f"{story.id}:character_state:{state.character_id}:ch:{chapter_index}",
                    type="character_state",
                    content=self._format_state(state),
                    chapter=chapter_index,
                    importance=8,
                    entities=[state.character_id],
                    tags=["character_state"],
                )
            )
        existing = {
            card.id: card
            for card in story.knowledge.retrieval_notes
            if card.chapter != chapter_index
        }
        for note in notes:
            existing[note.id] = note
        story.knowledge.retrieval_notes = sorted(
            existing.values(), key=lambda item: (item.chapter, item.importance)
        )
        return notes

    def _trim_retrieval_notes(self, story: Story) -> None:
        """当卡片数超过 max_notes 时按重要性+章节排序后裁剪。"""
        if len(story.knowledge.retrieval_notes) <= self.max_notes:
            return
        story.knowledge.retrieval_notes = sorted(
            story.knowledge.retrieval_notes,
            key=lambda item: (item.importance, item.chapter),
            reverse=True,
        )[: self.max_notes]
        story.knowledge.retrieval_notes.sort(key=lambda item: (item.chapter, item.importance))

    def _query_entities(self, story: Story, chapter_index: int, query: str) -> set[str]:
        """从大纲和查询中推断相关角色实体集合。"""
        entities: set[str] = set()
        try:
            outline = story.get_outline(chapter_index)
            if outline.pov_character:
                entities.add(outline.pov_character)
            query += " " + " ".join(
                [outline.title, outline.summary, outline.conflict, outline.pov_character or ""]
            )
        except KeyError:
            pass
        for character_id, character in story.design.characters.items():
            if character_id in query or (character.name and character.name in query):
                entities.add(character_id)
        return entities

    def _format_character_states(
        self, story: Story, entities: set[str], chapter_index: int
    ) -> list[str]:
        """格式化指定实体（或全部角色）的当前状态为可读字符串列表。"""
        candidates = entities or set(story.design.characters.keys())
        rows: list[str] = []
        for character_id in sorted(candidates):
            current = max(
                (
                    item
                    for item in story.knowledge.character_states.get(character_id, [])
                    if item.chapter < chapter_index
                ),
                key=lambda item: item.chapter,
                default=None,
            )
            if current:
                name = (
                    story.design.characters.get(character_id).name
                    if character_id in story.design.characters
                    else character_id
                )
                rows.append(f"{name}: {self._format_state(current)}")
        return rows[:12]

    def _format_pending_foreshadowings(
        self, story: Story, chapter_index: int, entities: set[str]
    ) -> list[str]:
        """格式化未回收伏笔列表，按与当前章节的距离排序。"""
        pending = [
            item
            for item in story.knowledge.foreshadowings
            if item.status == "pending" and item.created_chapter < chapter_index
        ]
        pending.sort(
            key=lambda item: (
                (item.target_chapter or chapter_index + 999) - chapter_index,
                -item.created_chapter,
            )
        )
        return [
            f"{item.id} created@ch{item.created_chapter}"
            + (f" target@ch{item.target_chapter}" if item.target_chapter else "")
            + f": {item.description}"
            for item in pending[:12]
        ]

    def _format_note(self, note: RetrievalNote) -> str:
        """格式化单张 RetrievalNote 为可读字符串。"""
        entities = f" entities={','.join(note.entities)}" if note.entities else ""
        return f"{note.type}@ch{note.chapter}{entities}: {note.content}"

    def _format_state(self, state: CharacterState) -> str:
        """格式化单个 CharacterState 为压缩后的可读字符串。"""
        parts = [
            f"ch{state.chapter}",
            state.emotional_state,
            state.location,
            "; ".join(state.knowledge_gained[:3]),
        ]
        if state.relationship_changes:
            parts.append(
                "relations="
                + ", ".join(f"{k}:{v}" for k, v in list(state.relationship_changes.items())[:4])
            )
        return compress(" | ".join(part for part in parts if part), 320)

    def _arc_index(self, chapter_index: int) -> int:
        """根据章节编号计算所属的故事弧编号。"""
        return max(1, (chapter_index - 1) // self.chapters_per_arc + 1)
