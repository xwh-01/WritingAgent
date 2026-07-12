"""Unified facade for long-form continuity subsystems."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from novelforge.agents.memory_extractor import MemoryExtractionResult, MemoryExtractorAgent
from novelforge.core.models import CharacterState, Foreshadowing, Story
from novelforge.llm.base import LLMClient
from novelforge.longform.causality import CausalityTracker
from novelforge.longform.character_state import CharacterStateTracker
from novelforge.longform.foreshadowing import ForeshadowingTracker
from novelforge.longform.fact_ledger import CharacterFactLedger
from novelforge.longform.memory_engine import MemoryEngineV2
from novelforge.longform.pacing import PacingAnalyzer
from novelforge.longform.summaries import SummaryManager

if TYPE_CHECKING:
    from novelforge.core.config import MemoryRankerConfig


class LongformManager:
    """长篇写作的统一协调器，聚合伏笔、因果、记忆、摘要、节奏和角色状态等子系统。

    为上层提供 process_new_chapter（处理新章节）和 get_enhanced_context（生成增强上下文）两个主要入口。
    """

    def __init__(self, llm: LLMClient | None = None, memory_ranker_config: "MemoryRankerConfig | None" = None) -> None:
        """初始化所有子系统。

        Args:
            llm: 可选的 LLM 客户端，为 None 时各子系统使用规则回退。
            memory_ranker_config: MemoryRanker 配置，为 None 时使用默认权重。
        """
        self.foreshadowing_tracker = ForeshadowingTracker(llm)
        self.causality_tracker = CausalityTracker(llm)
        self.memory_extractor = MemoryExtractorAgent(llm)
        self.summary_manager = SummaryManager(llm)
        self.memory_engine = MemoryEngineV2(memory_ranker_config=memory_ranker_config)
        self.pacing_analyzer = PacingAnalyzer()
        self.character_state_tracker = CharacterStateTracker(llm)
        self.fact_ledger = CharacterFactLedger()
        self.pacing_history: dict[str, list[dict[str, Any]]] = {}
        self.pacing_warnings: dict[str, str] = {}

    def process_new_chapter(self, story: Story, chapter_index: int, content: str) -> dict[str, Any]:
        """处理新章节的完整管线。

        依次执行：记忆提取 → 应用提取结果 → 章节摘要 → 因果事件 → 伏笔分析 → 角色状态 → 节奏分析 → 卷摘要 → 记忆引擎更新。
        返回包含各阶段结果的字典。
        """
        extraction = self.memory_extractor.extract_chapter_memory(story, chapter_index, content)
        self._apply_extraction(story, extraction)
        summary = self.summary_manager.generate_chapter_summary(story, chapter_index, content)
        events = self.causality_tracker.extract_events_from_chapter(story, chapter_index, content)
        summary.key_events = [event.id for event in events]
        foreshadowings = self.foreshadowing_tracker.analyze_new_chapter(story, chapter_index, content)
        states = self.character_state_tracker.extract_state_from_chapter(
            story, chapter_index, content, list(story.content.characters.values())
        )
        facts = self.fact_ledger.rebuild_from_states(story)
        pacing = self.pacing_analyzer.analyze_chapter(content)
        key = str(story.id)
        history = [item for item in self.pacing_history.get(key, []) if item.get("chapter") != chapter_index]
        history.append({"chapter": chapter_index, **pacing})
        history.sort(key=lambda item: item["chapter"])
        self.pacing_history[key] = history
        warning = self.pacing_analyzer.check_pacing_trend(history[-5:])
        self.pacing_warnings[key] = warning

        volume = max(1, (chapter_index - 1) // self.summary_manager.chapters_per_volume + 1)
        self.summary_manager.generate_volume_summary(story, volume)
        memory = self.memory_engine.process_chapter(
            story,
            chapter_index,
            summary,
            events,
            foreshadowings,
            states,
        )
        return {
            "summary": summary,
            "events": events,
            "foreshadowings": foreshadowings,
            "character_states": states,
            "character_facts": facts,
            "pacing": pacing,
            "pacing_warning": warning,
            "extraction": extraction,
            "memory": memory,
        }

    def _apply_extraction(self, story: Story, extraction: MemoryExtractionResult) -> None:
        """将 MemoryExtractor 的提取结果合并到 story 中。

        合并角色、世界设定、关系和连续性约束，对已有内容做增量更新。
        """
        for character in extraction.characters:
            existing = story.content.characters.get(character.id)
            if existing is None:
                story.content.characters[character.id] = character
                continue
            if character.name:
                existing.name = character.name
            if character.age != "unknown":
                existing.age = character.age
            if character.appearance:
                existing.appearance = character.appearance
            if character.personality:
                existing.personality = self._merge_text(existing.personality, character.personality)
            if character.motivation:
                existing.motivation = character.motivation
            if character.weakness:
                existing.weakness = character.weakness
            existing.relationships.update(character.relationships)
            for secret in character.secrets:
                if secret not in existing.secrets:
                    existing.secrets.append(secret)
            if character.arc:
                existing.arc = self._merge_text(existing.arc, character.arc)

        existing_world = {(item.category, item.content) for item in story.content.world_settings}
        for setting in extraction.world_settings:
            key = (setting.category, setting.content)
            if key not in existing_world:
                story.content.world_settings.append(setting)
                existing_world.add(key)

        for relation in extraction.relationships:
            source = story.content.characters.get(relation.source)
            target = story.content.characters.get(relation.target)
            if source and target:
                source.relationships[target.id] = relation.relation
                target.relationships.setdefault(source.id, relation.relation)

        for constraint in extraction.continuity_constraints:
            if constraint not in story.memory.story_bible.continuity_constraints:
                story.memory.story_bible.continuity_constraints.append(constraint)

    def _merge_text(self, old: str, new: str) -> str:
        """合并两段文本：如果 new 已包含在 old 中则保留 old，否则用分号拼接。"""
        if not old:
            return new
        if new in old:
            return old
        return f"{old}; {new}"

    def get_enhanced_context(self, chapter_index: int, story: Story, query: str = "") -> str:
        """生成增强写作上下文，聚合记忆引擎上下文包、滚动摘要、未回收伏笔和角色当前状态。"""
        sections: list[str] = []
        fact_context = self.fact_ledger.format_context(story, chapter_index)
        if fact_context:
            sections.append(fact_context)
        pack = self.memory_engine.build_context_pack(story, chapter_index, query=query)
        packed_context = self.memory_engine.format_context_pack(pack)
        if packed_context.strip() != "Memory Engine v2 Context Pack":
            sections.append(packed_context)

        rolling = self.summary_manager.get_rolling_context(story, chapter_index)
        if rolling.strip() != "长篇滚动记忆:":
            sections.append(rolling)

        pending = [
            item for item in self.foreshadowing_tracker.get_pending(story)
            if item.created_chapter < chapter_index
        ]
        if pending:
            sections.append(
                "未回收伏笔:\n"
                + "\n".join(
                    f"- {item.id}: {item.description}"
                    + (f"（计划第{item.target_chapter}章回收）" if item.target_chapter else "")
                    for item in pending
                )
            )

        outline = None
        try:
            outline = story.get_outline(chapter_index)
        except KeyError:
            pass
        character_ids = set(story.content.characters)
        if outline and outline.pov_character:
            character_ids.add(outline.pov_character)
        states: list[CharacterState] = []
        for character_id in character_ids:
            state = max(
                (item for item in story.memory.states.get(character_id, []) if item.chapter < chapter_index),
                key=lambda item: item.chapter,
                default=None,
            )
            if state:
                states.append(state)
        if states:
            sections.append("角色当前状态:\n" + json.dumps([state.model_dump() for state in states], ensure_ascii=False))

        if story.memory.causal_events:
            recent = sorted(
                (event for event in story.memory.causal_events if event.chapter < chapter_index),
                key=lambda event: event.chapter,
            )[-5:]
            sections.append("最近因果事件:\n" + "\n".join(f"- {event.id}: {event.description}" for event in recent))
        return "\n\n".join(sections)

    def review_chapter_consistency(self, story: Story, chapter_index: int, content: str) -> dict[str, list[str]]:
        """审查章节一致性，返回伏笔、节奏和角色状态三方面的问题列表。"""
        pending_due = [
            f"伏笔 {item.id} 计划在第{item.target_chapter}章回收，但仍为 pending：{item.description}"
            for item in story.memory.foreshadowings
            if item.status == "pending" and item.target_chapter is not None and item.target_chapter <= chapter_index
        ]
        pacing = self.pacing_analyzer.analyze_chapter(content)
        pacing_warning = self.pacing_analyzer.check_pacing_trend(
            self.pacing_history.get(str(story.id), []) + [{"chapter": chapter_index, **pacing}]
        )
        state_issues: list[str] = []
        for character_id, states in story.memory.states.items():
            previous = max((state for state in states if state.chapter < chapter_index), key=lambda s: s.chapter, default=None)
            current = max((state for state in states if state.chapter == chapter_index), key=lambda s: s.chapter, default=None)
            if current:
                state_issues.extend(self.character_state_tracker.check_consistency(previous, current))
        return {
            "foreshadowing_issues": pending_due,
            "pacing_issues": [] if pacing_warning == "节奏趋势正常。" else [pacing_warning],
            "character_state_issues": state_issues,
        }

    def add_foreshadowing(
        self,
        story: Story,
        description: str,
        created_chapter: int,
        target_chapter: int | None = None,
        notes: str = "",
    ) -> Foreshadowing:
        """手动添加一条伏笔到故事中，通过 ForeshadowingTracker 注册并返回。"""
        item = Foreshadowing(
            id=f"fs-manual-{len(story.memory.foreshadowings) + 1}",
            description=description,
            created_chapter=created_chapter,
            target_chapter=target_chapter,
            notes=notes,
        )
        return self.foreshadowing_tracker.register(story, item)
