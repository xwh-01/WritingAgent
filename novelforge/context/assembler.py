"""Build concise writing context from story state and memory backends."""

from __future__ import annotations

import json
from typing import Any

from novelforge.core.models import Story
from novelforge.longform.manager import LongformManager
from novelforge.longform.ranker import MemoryRanker
from novelforge.memory.interfaces import IFTSStore, IGraphStore, IVectorStore


class ContextAssembler:
    def __init__(
        self,
        vector_store: IVectorStore,
        graph_store: IGraphStore,
        text_store: IFTSStore,
        max_context_tokens: int = 6000,
        longform_manager: LongformManager | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.text_store = text_store
        self.max_context_tokens = max_context_tokens
        self.longform_manager = longform_manager
        self.ranker = MemoryRanker()

    def assemble_writing_context(self, chapter_index: int, story: Story) -> str:
        outline = story.get_outline(chapter_index)
        query = " ".join(
            part
            for part in [outline.title, outline.summary, outline.conflict, outline.pov_character or ""]
            if part
        )
        sections: list[tuple[int, str]] = [
            (100, f"故事前提: {story.premise}"),
            (95, f"文风指南: {story.style_guide or '保持清晰、连贯、有画面感。'}"),
            (90, f"本章大纲: {json.dumps(outline.model_dump(), ensure_ascii=False)}"),
        ]
        chapter = story.chapters.get(chapter_index)
        if chapter and chapter.beats:
            sections.append((85, "本章节拍: " + json.dumps([b.model_dump() for b in chapter.beats], ensure_ascii=False)))
        if outline.pov_character:
            graph = self.graph_store.get_ego_network(outline.pov_character, depth=1)
            sections.append((70, "视角角色关系网: " + json.dumps(graph, ensure_ascii=False)))

        entities = self._query_entities(story, query)
        recalled: list[dict[str, Any]] = []
        for collection in ("characters", "world", "plot_summaries", "memory_cards"):
            for item in self.vector_store.query(collection, query, k=12):
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault("collection", collection)
                item = dict(item)
                item["metadata"] = metadata
                recalled.append(item)
        ranked = self.ranker.rank_vector_hits(recalled, query, chapter_index, entities=entities, limit=12)
        for ranked_item in ranked:
            item = ranked_item.item
            collection = item.get("metadata", {}).get("collection", "memory")
            sections.append((50, f"相关记忆[{collection} score={ranked_item.score:.1f}]: {item['document']}"))

        for result in self.text_store.search(query, limit=5):
            sections.append((40, f"全文检索片段: {result[:500]}"))

        if self.longform_manager is not None:
            enhanced = self.longform_manager.get_enhanced_context(chapter_index, story, query=query)
            if enhanced:
                sections.append((88, enhanced))

        sections.sort(key=lambda item: item[0], reverse=True)
        context = "\n\n".join(text for _, text in sections)
        return self._truncate(context)

    def _truncate(self, text: str) -> str:
        max_chars = self.max_context_tokens * 4
        return text[:max_chars]

    def _query_entities(self, story: Story, query: str) -> set[str]:
        entities: set[str] = set()
        for character_id, character in story.characters.items():
            if character_id in query or (character.name and character.name in query):
                entities.add(character_id)
        return entities
