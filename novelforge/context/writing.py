"""Build bounded writing context from canonical knowledge and search indexes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from novelforge.domain import Story
from novelforge.indexes.interfaces import IFTSStore, IVectorStore
from novelforge.longform.knowledge_system import StoryKnowledgeSystem
from novelforge.longform.retrieval import RetrievalRanker

if TYPE_CHECKING:
    from novelforge.core.config import RetrievalConfig


class WritingContextAssembler:
    """Build the only context payload passed into chapter generation."""

    def __init__(
        self,
        vector_store: IVectorStore,
        text_store: IFTSStore,
        max_context_tokens: int = 6000,
        knowledge_system: StoryKnowledgeSystem | None = None,
        retrieval_config: "RetrievalConfig | None" = None,
    ) -> None:
        """Initialize retrieval projections and the context budget."""
        self.vector_store = vector_store
        self.text_store = text_store
        self.max_context_tokens = max_context_tokens
        self.knowledge_system = knowledge_system
        self.ranker = RetrievalRanker(retrieval_config)
        self.last_context_stats: dict[str, Any] = {}

    def build(self, chapter_index: int, story: Story) -> str:
        """拼装指定章节的写作上下文：大纲、角色关系、向量记忆、全文检索和长文摘要。
        返回按重要性排序并截断后的文本块。
        """
        outline = story.get_outline(chapter_index)
        query = " ".join(
            part
            for part in [
                outline.title,
                outline.summary,
                outline.conflict,
                outline.pov_character or "",
            ]
            if part
        )
        sections: list[tuple[int, str]] = [
            (100, f"故事前提: {story.premise}"),
            (95, f"文风指南: {story.style_guide or '保持清晰、连贯、有画面感。'}"),
            (90, f"本章大纲: {json.dumps(outline.model_dump(), ensure_ascii=False)}"),
        ]
        if story.design.characters:
            sections.append(
                (
                    94,
                    "作者设定角色（最高优先级）: "
                    + json.dumps(
                        [item.model_dump() for item in story.design.characters.values()],
                        ensure_ascii=False,
                    ),
                )
            )
        if story.design.world_settings:
            sections.append(
                (
                    93,
                    "作者设定世界规则（最高优先级）: "
                    + json.dumps(
                        [item.model_dump() for item in story.design.world_settings],
                        ensure_ascii=False,
                    ),
                )
            )
        if story.knowledge.character_observations:
            sections.append(
                (
                    78,
                    "正文派生角色观察: "
                    + json.dumps(
                        [item.model_dump() for item in story.knowledge.character_observations],
                        ensure_ascii=False,
                    ),
                )
            )
        if story.knowledge.world_facts:
            sections.append(
                (
                    77,
                    "正文派生世界事实: "
                    + json.dumps(
                        [item.model_dump() for item in story.knowledge.world_facts],
                        ensure_ascii=False,
                    ),
                )
            )
        chapter = story.manuscript.chapters.get(chapter_index)
        if chapter and chapter.beats:
            sections.append(
                (
                    85,
                    "本章节拍: "
                    + json.dumps([b.model_dump() for b in chapter.beats], ensure_ascii=False),
                )
            )
        if story.knowledge.relationships:
            sections.append(
                (
                    76,
                    "已发生角色关系: "
                    + json.dumps(
                        [item.model_dump() for item in story.knowledge.relationships],
                        ensure_ascii=False,
                    ),
                )
            )

        entities = self._query_entities(story, query)
        recalled: list[dict[str, Any]] = []
        vector_hits_count = 0
        for collection in ("plot_summaries", "knowledge_notes"):
            for item in self.vector_store.query(
                collection,
                query,
                k=50,
                story_id=str(story.id),
                max_chapter=chapter_index - 1,
            ):
                vector_hits_count += 1
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault("collection", collection)
                item = dict(item)
                item["metadata"] = metadata
                recalled.append(item)
        ranked = self.ranker.rank_vector_hits(
            recalled, query, chapter_index, entities=entities, limit=12
        )
        for ranked_item in ranked:
            item = ranked_item.item
            collection = item.get("metadata", {}).get("collection", "knowledge")
            sections.append(
                (50, f"检索知识[{collection} score={ranked_item.score:.1f}]: {item['document']}")
            )

        text_hits = self.text_store.search(
            query,
            limit=5,
            story_id=str(story.id),
            max_chapter=chapter_index - 1,
        )
        for result in text_hits:
            sections.append((40, f"全文检索片段: {result[:500]}"))

        has_longform_context = False
        if self.knowledge_system is not None:
            enhanced = self.knowledge_system.build_writing_context(
                chapter_index, story, query=query
            )
            if enhanced:
                has_longform_context = True
                sections.append((88, enhanced))

        self.last_context_stats = {
            "story_id": str(story.id),
            "chapter_index": chapter_index,
            "query": query,
            "vector_hits_count": vector_hits_count,
            "ranked_hits_count": len(ranked),
            "text_hits_count": len(text_hits),
            "knowledge_context": has_longform_context,
            "retrieval_hits_count": len(ranked)
            + len(text_hits)
            + (1 if has_longform_context else 0),
        }
        sections.sort(key=lambda item: item[0], reverse=True)
        context = "\n\n".join(text for _, text in sections)
        return self._truncate(context)

    def _truncate(self, text: str) -> str:
        """按 max_context_tokens 估算的字符数截断文本。

        在 token 边界不精确的约束下，尽量在段落/句子边界截断以避免
        在 JSON 结构或词语中间切断。
        """
        max_chars = self.max_context_tokens * 4
        if len(text) <= max_chars:
            return text
        # Walk back to the nearest double-newline (section boundary) or
        # single-newline (line boundary) to avoid mid-structure cuts.
        truncated = text[:max_chars]
        for boundary in ("\n\n", "\n", "。", "！", "？", ".", "!", "?"):
            last = truncated.rfind(boundary, max_chars - 500)
            if last > max_chars * 0.6:
                return truncated[: last + len(boundary)]
        return truncated

    def _query_entities(self, story: Story, query: str) -> set[str]:
        """从查询字符串中识别引用的角色实体 ID。"""
        entities: set[str] = set()
        for character_id, character in story.design.characters.items():
            if character_id in query or (character.name and character.name in query):
                entities.add(character_id)
        return entities
