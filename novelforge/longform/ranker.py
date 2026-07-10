"""Rule-based memory reranking for long-form retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from novelforge.core.models import MemoryCard

if TYPE_CHECKING:
    from novelforge.core.config import MemoryRankerConfig


@dataclass(frozen=True)
class RankedMemory:
    """排序后的记忆条目，包含原始对象、评分和评分原因。"""
    item: Any
    score: float
    reasons: tuple[str, ...] = ()


class MemoryRanker:
    """Explainable reranker for vector hits and structured memory cards.

    权重优先级（从高到低）：
    - foreshadowing (6.0): 遗忘未回收伏笔 → 叙事断裂
    - character_state (6.5): 角色状态漂移 → 最常见的一致性错误
    - causal_event (4.0): 因果链断裂 → 影响逻辑但出现频率低
    - world / character (3.0): 已有冗余检索路径
    - chapter_summary (2.0): 避免与滚动摘要重复注入
    """

    def __init__(self, config: "MemoryRankerConfig | None" = None) -> None:
        """初始化重排序器，使用可配置的权重。

        Args:
            config: MemoryRankerConfig 实例，为 None 时使用默认权重。
        """
        if config is not None:
            self._type_weights = dict(config.type_weights)
            self._recency_max = config.recency_max
            self._recency_decay_base = config.recency_decay_base
            self._entity_match_bonus = config.entity_match_bonus
            self._query_match_bonus_per_term = config.query_match_bonus_per_term
            self._query_match_max = config.query_match_max
        else:
            self._type_weights = {
                "foreshadowing": 6.0,
                "character_state": 6.5,
                "causal_event": 4.0,
                "world": 3.0,
                "character": 3.0,
                "chapter_summary": 2.0,
            }
            self._recency_max = 5.0
            self._recency_decay_base = 20.0
            self._entity_match_bonus = 7.0
            self._query_match_bonus_per_term = 2.0
            self._query_match_max = 8.0

    @property
    def type_weights(self) -> dict[str, float]:
        """暴露权重字典以保持向后兼容（供外部只读访问）。"""
        return dict(self._type_weights)

    def rank_vector_hits(
        self,
        hits: list[dict[str, Any]],
        query: str,
        current_chapter: int,
        entities: set[str] | None = None,
        limit: int = 12,
    ) -> list[RankedMemory]:
        """对向量搜索结果进行多维重排序。

        综合考虑类型权重、时间新鲜度、查询词匹配和实体相关性，返回 top-limit 结果。
        """
        entities = entities or set()
        query_terms = self._terms(query)
        ranked: list[RankedMemory] = []
        for hit in hits:
            metadata = hit.get("metadata") or {}
            document = str(hit.get("document") or "")
            score = float(hit.get("score") or 0.0) * 10.0
            reasons: list[str] = ["vector"]

            item_type = str(metadata.get("type") or "")
            if item_type in self._type_weights:
                score += self._type_weights[item_type]
                reasons.append(f"type:{item_type}")

            chapter = self._int_or_none(metadata.get("chapter"))
            if chapter is not None:
                score += self._recency_score(current_chapter, chapter)
                reasons.append("recency")

            overlap = query_terms.intersection(self._terms(document + " " + " ".join(str(v) for v in metadata.values())))
            if overlap:
                score += min(self._query_match_max, len(overlap) * self._query_match_bonus_per_term)
                reasons.append("query")

            metadata_entities = set(str(metadata.get("entities", "")).split(",")) | {str(metadata.get("character_id", ""))}
            metadata_entities.discard("")
            if entities.intersection(metadata_entities):
                score += self._entity_match_bonus
                reasons.append("entity")

            ranked.append(RankedMemory(hit, score, tuple(reasons)))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def rank_cards(
        self,
        cards: list[MemoryCard],
        query: str,
        current_chapter: int,
        entities: set[str] | None = None,
        limit: int = 12,
    ) -> list[RankedMemory]:
        """对 MemoryCard 列表进行多维度打分排序。

        考虑重要性、类型权重、时间新鲜度、实体匹配、查询匹配和最后出现时间，返回 top-limit 结果。
        """
        entities = entities or set()
        query_terms = self._terms(query)
        ranked: list[RankedMemory] = []
        for card in cards:
            score = float(card.importance)
            reasons: list[str] = ["importance"]

            score += self._type_weights.get(card.type, 0.0)
            if card.type in self._type_weights:
                reasons.append(f"type:{card.type}")

            score += self._recency_score(current_chapter, card.chapter)
            reasons.append("recency")

            if entities.intersection(card.entities):
                score += self._entity_match_bonus
                reasons.append("entity")

            overlap = query_terms.intersection(self._terms(card.content + " " + " ".join(card.tags)))
            if overlap:
                score += min(self._query_match_max, len(overlap) * self._query_match_bonus_per_term)
                reasons.append("query")

            if card.last_seen_chapter and card.last_seen_chapter < current_chapter:
                score += max(0.0, 2.0 - ((current_chapter - card.last_seen_chapter) / 100.0))
                reasons.append("last_seen")

            ranked.append(RankedMemory(card, score, tuple(reasons)))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _recency_score(self, current_chapter: int, item_chapter: int) -> float:
        """计算时间新鲜度分数：越近的章节得分越高，未来章节得负分。"""
        if item_chapter > current_chapter:
            return -4.0  # 未来章节固定惩罚
        distance = max(0, current_chapter - item_chapter)
        return max(0.0, self._recency_max - (distance / self._recency_decay_base))

    def _terms(self, text: str) -> set[str]:
        """提取文本中的词条集合，支持中英文（长度 >= 2 的字符序列）。"""
        return {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", text)}

    def _int_or_none(self, value: Any) -> int | None:
        """安全地将任意值转为 int，失败时返回 None。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
