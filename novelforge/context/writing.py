"""Build bounded writing context from canonical knowledge and search indexes."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from novelforge.domain import Beat, Story
from novelforge.indexes.interfaces import IFTSStore, IGraphStore, IVectorStore
from novelforge.longform.knowledge_system import StoryKnowledgeSystem
from novelforge.longform.retrieval import RetrievalRanker

if TYPE_CHECKING:
    from novelforge.core.config import RetrievalConfig


@dataclass(frozen=True)
class ContextEvidence:
    """One compact, source-addressable fact included in a writing prompt."""

    label: str
    content: str
    source: str
    reason: str
    priority: int

    def render(self) -> str:
        return (
            f"[{self.label} | 来源: {self.source} | 入选原因: {self.reason}]\n"
            f"{self.content}"
        )


@dataclass(frozen=True)
class SceneWritingContext:
    """The bounded, auditable context supplied to one scene writer."""

    chapter_index: int
    scene_index: int
    query: str
    content: str
    evidence: tuple[ContextEvidence, ...]
    stats: dict[str, Any]


class WritingContextAssembler:
    """Build the only context payload passed into chapter generation."""

    def __init__(
        self,
        vector_store: IVectorStore,
        text_store: IFTSStore,
        max_context_tokens: int = 6000,
        knowledge_system: StoryKnowledgeSystem | None = None,
        retrieval_config: "RetrievalConfig | None" = None,
        graph_store: IGraphStore | None = None,
    ) -> None:
        """Initialize retrieval projections and the context budget."""
        self.vector_store = vector_store
        self.text_store = text_store
        self.max_context_tokens = max_context_tokens
        self.knowledge_system = knowledge_system
        self.graph_store = graph_store
        self.ranker = RetrievalRanker(retrieval_config)
        self.last_context_stats: dict[str, Any] = {}
        self.last_scene_context_stats: dict[int, dict[str, Any]] = {}

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

    def build_scene_context(
        self,
        chapter_index: int,
        story: Story,
        scene: Beat,
        *,
        token_budget: int | None = None,
    ) -> SceneWritingContext:
        """Build a scene-specific slice of canonical long-form knowledge.

        Chapter planning may use broad context, but prose generation needs a
        smaller, evidence-labelled packet.  This keeps the writer grounded in
        facts that are relevant to the current POV, location, conflict and
        participating characters while preserving where every fact came from.
        """
        query = self._scene_query(story, scene)
        entities = self._scene_entities(story, scene, query)
        evidence = self._scene_evidence(story, chapter_index, scene, query, entities)
        budget = token_budget or max(700, self.max_context_tokens // 3)
        selected, content, used_tokens = self._fit_evidence(evidence, budget)
        stats = {
            "story_id": str(story.id),
            "chapter_index": chapter_index,
            "scene_index": scene.scene_index,
            "query": query,
            "entity_ids": sorted(entities),
            "token_budget": budget,
            "estimated_tokens": used_tokens,
            "candidate_evidence_count": len(evidence),
            "selected_evidence_count": len(selected),
            "selected_labels": [item.label for item in selected],
            "sources": [item.source for item in selected],
        }
        self.last_scene_context_stats[scene.scene_index] = stats
        self.last_context_stats.setdefault("scene_contexts", {})[scene.scene_index] = stats
        return SceneWritingContext(
            chapter_index=chapter_index,
            scene_index=scene.scene_index,
            query=query,
            content=content,
            evidence=tuple(selected),
            stats=stats,
        )

    def _truncate(self, text: str) -> str:
        """Keep whole sections inside a conservative Chinese/English token budget."""
        if self._estimate_tokens(text) <= self.max_context_tokens:
            return text
        kept: list[str] = []
        used = 0
        for section in text.split("\n\n"):
            section_tokens = self._estimate_tokens(section)
            if used + section_tokens > self.max_context_tokens:
                continue
            kept.append(section)
            used += section_tokens
        return "\n\n".join(kept)

    def _query_entities(self, story: Story, query: str) -> set[str]:
        """从查询字符串中识别引用的角色实体 ID。"""
        entities: set[str] = set()
        for character_id, character in story.design.characters.items():
            if character_id in query or (character.name and character.name in query):
                entities.add(character_id)
        return entities

    def _scene_query(self, story: Story, scene: Beat) -> str:
        return " ".join(
            str(part)
            for part in (
                story.title,
                scene.title,
                scene.purpose,
                scene.goal,
                scene.conflict,
                scene.obstacle,
                scene.location,
                scene.time_context,
                " ".join(scene.participating_characters),
                scene.pov_character,
                " ".join(scene.must_happen),
                " ".join(scene.information_revealed),
            )
            if part
        )

    def _scene_entities(self, story: Story, scene: Beat, query: str) -> set[str]:
        entities = self._query_entities(story, query)
        names = {*scene.participating_characters}
        if scene.pov_character:
            names.add(scene.pov_character)
        for character_id, character in story.design.characters.items():
            if character_id in names or character.name in names:
                entities.add(character_id)
        return entities

    def _scene_evidence(
        self,
        story: Story,
        chapter_index: int,
        scene: Beat,
        query: str,
        entities: set[str],
    ) -> list[ContextEvidence]:
        evidence: list[ContextEvidence] = []

        for character_id in sorted(entities):
            character = story.design.characters.get(character_id)
            if character is not None:
                evidence.append(
                    ContextEvidence(
                        "作者角色设定",
                        json.dumps(character.model_dump(), ensure_ascii=False),
                        "作者设定",
                        "场景参与者或 POV",
                        100,
                    )
                )
            states = [
                item
                for item in story.knowledge.character_states.get(character_id, [])
                if item.chapter < chapter_index
            ]
            if states:
                latest = max(states, key=lambda item: item.chapter)
                evidence.append(
                    ContextEvidence(
                        "角色当前状态",
                        json.dumps(latest.model_dump(), ensure_ascii=False),
                        f"第{latest.chapter}章正式正文",
                        "场景参与者的最近可见状态",
                        96,
                    )
                )

        for fact in story.knowledge.character_facts:
            if fact.character_id not in entities:
                continue
            if not fact.user_confirmed or fact.valid_from_chapter > chapter_index:
                continue
            if fact.valid_until_chapter is not None and fact.valid_until_chapter < chapter_index:
                continue
            evidence.append(
                ContextEvidence(
                    "已确认角色事实",
                    json.dumps(fact.model_dump(), ensure_ascii=False),
                    f"作者确认 / 第{fact.source_chapter or fact.valid_from_chapter}章",
                    "参与角色的有效事实，优先于自动推断",
                    99,
                )
            )

        world_items = [*story.design.world_settings, *story.knowledge.world_facts]
        for item in self._rank_models(world_items, query, limit=8):
            source_chapter = getattr(item, "source_chapter", None)
            if source_chapter is not None and source_chapter >= chapter_index:
                continue
            evidence.append(
                ContextEvidence(
                    "世界规则" if source_chapter is None else "正文派生世界事实",
                    json.dumps(item.model_dump(), ensure_ascii=False),
                    "作者设定" if source_chapter is None else f"第{source_chapter}章正式正文",
                    "与场景地点、冲突或物件匹配",
                    94 if source_chapter is None else 84,
                )
            )

        pending = [
            item
            for item in story.knowledge.foreshadowings
            if str(item.status) == "pending" and item.created_chapter < chapter_index
        ]
        for item in self._rank_models(pending, query, limit=6):
            evidence.append(
                ContextEvidence(
                    "待处理伏笔",
                    json.dumps(item.model_dump(), ensure_ascii=False),
                    f"第{item.created_chapter}章正式正文",
                    "避免遗忘、误回收或提前泄露",
                    92,
                )
            )

        events = [item for item in story.knowledge.timeline if item.chapter < chapter_index]
        for item in self._rank_models(events, query, limit=6):
            evidence.append(
                ContextEvidence(
                    "既有因果事件",
                    json.dumps(item.model_dump(), ensure_ascii=False),
                    f"第{item.chapter}章正式正文",
                    "场景冲突需要承接既有因果",
                    89,
                )
            )

        evidence.extend(self._graph_evidence(story, entities))
        evidence.extend(self._vector_evidence(story, chapter_index, query, entities))
        return sorted(evidence, key=lambda item: (-item.priority, item.label, item.source))

    def _graph_evidence(self, story: Story, entities: set[str]) -> list[ContextEvidence]:
        if self.graph_store is None:
            return []
        evidence: list[ContextEvidence] = []
        story_id = str(story.id)
        for character_id in sorted(entities):
            node_id = f"{story_id}:character:{character_id}"
            network = self.graph_store.get_ego_network(node_id, depth=1)
            nodes = network.get("nodes") or {}
            edges = network.get("edges") or []
            if len(nodes) <= 1 and not edges:
                continue
            compact_nodes = {
                key: {
                    field: value
                    for field, value in value.items()
                    if field in {"id", "name", "personality", "motivation", "relationships"}
                }
                for key, value in nodes.items()
            }
            evidence.append(
                ContextEvidence(
                    "角色关系图",
                    json.dumps({"nodes": compact_nodes, "edges": edges}, ensure_ascii=False),
                    "可重建关系图索引（来自作者设定和已提交正文）",
                    "场景参与角色的一度关系邻域",
                    88,
                )
            )
        return evidence

    def _vector_evidence(
        self,
        story: Story,
        chapter_index: int,
        query: str,
        entities: set[str],
    ) -> list[ContextEvidence]:
        recalled: list[dict[str, Any]] = []
        for collection in (
            "plot_summaries",
            "knowledge_notes",
            "characters",
            "world",
            "character_facts",
        ):
            for item in self.vector_store.query(
                collection,
                query,
                k=12,
                story_id=str(story.id),
                max_chapter=chapter_index - 1,
            ):
                clone = dict(item)
                metadata = dict(clone.get("metadata") or {})
                if collection == "character_facts":
                    if str(metadata.get("confirmed", "")).lower() not in {"true", "1"}:
                        continue
                    valid_until = self._as_int(metadata.get("valid_until_chapter"))
                    if valid_until is not None and valid_until > 0 and valid_until < chapter_index:
                        continue
                metadata["collection"] = collection
                clone["metadata"] = metadata
                recalled.append(clone)
        ranked = self.ranker.rank_vector_hits(
            recalled, query, chapter_index, entities=entities, limit=10
        )
        return [
            ContextEvidence(
                "检索记忆",
                str(item.item.get("document") or "")[:900],
                str(item.item.get("metadata", {}).get("collection") or "向量索引"),
                "语义、实体、类型和时效重排序命中: " + ", ".join(item.reasons),
                70,
            )
            for item in ranked
            if str(item.item.get("document") or "").strip()
        ]

    def _rank_models(self, values: list[Any], query: str, limit: int) -> list[Any]:
        scored = [
            (self._relevance_score(json.dumps(item.model_dump(), ensure_ascii=False), query), item)
            for item in values
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _fit_evidence(
        self, evidence: list[ContextEvidence], token_budget: int
    ) -> tuple[list[ContextEvidence], str, int]:
        selected: list[ContextEvidence] = []
        rendered: list[str] = []
        used = 0
        seen: set[tuple[str, str]] = set()

        def include(item: ContextEvidence) -> bool:
            nonlocal used
            key = (item.label, item.content)
            if key in seen:
                return False
            seen.add(key)
            text = item.render()
            tokens = self._estimate_tokens(text)
            if used + tokens > token_budget:
                return False
            selected.append(item)
            rendered.append(text)
            used += tokens
            return True

        # Do not let a large character or world profile crowd every
        # long-form safeguard out of a scene prompt.  If available, reserve one
        # compact fact from each canonical continuity dimension first.
        for label in (
            "已确认角色事实",
            "世界规则",
            "待处理伏笔",
            "既有因果事件",
            "角色关系图",
        ):
            for item in evidence:
                if item.label == label and include(item):
                    break
        for item in evidence:
            include(item)
        return selected, "\n\n".join(rendered), used

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Conservative approximation when a provider tokenizer is unavailable."""
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        non_cjk = max(0, len(text) - cjk)
        return max(1, math.ceil(cjk / 1.5 + non_cjk / 4))

    def _relevance_score(self, content: str, query: str) -> int:
        if not query:
            return 0
        query_terms = self._terms(query)
        content_terms = self._terms(content)
        return len(query_terms.intersection(content_terms))

    @staticmethod
    def _terms(text: str) -> set[str]:
        latin = {item.lower() for item in re.findall(r"[A-Za-z0-9_]{2,}", text)}
        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        grams = {
            run[index : index + size]
            for run in cjk_runs
            for size in (2, 3)
            for index in range(max(0, len(run) - size + 1))
        }
        return latin | grams

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = ["ContextEvidence", "SceneWritingContext", "WritingContextAssembler"]
