"""Rule-based memory reranking for long-form retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from novelforge.core.models import MemoryCard


@dataclass(frozen=True)
class RankedMemory:
    item: Any
    score: float
    reasons: tuple[str, ...] = ()


class MemoryRanker:
    """Explainable reranker for vector hits and structured memory cards."""

    TYPE_WEIGHTS = {
        "foreshadowing": 6.0,
        "character_state": 5.0,
        "causal_event": 4.0,
        "chapter_summary": 3.0,
        "world": 3.0,
        "character": 3.0,
    }

    def rank_vector_hits(
        self,
        hits: list[dict[str, Any]],
        query: str,
        current_chapter: int,
        entities: set[str] | None = None,
        limit: int = 12,
    ) -> list[RankedMemory]:
        entities = entities or set()
        query_terms = self._terms(query)
        ranked: list[RankedMemory] = []
        for hit in hits:
            metadata = hit.get("metadata") or {}
            document = str(hit.get("document") or "")
            score = float(hit.get("score") or 0.0) * 10.0
            reasons: list[str] = ["vector"]

            item_type = str(metadata.get("type") or "")
            if item_type in self.TYPE_WEIGHTS:
                score += self.TYPE_WEIGHTS[item_type]
                reasons.append(f"type:{item_type}")

            chapter = self._int_or_none(metadata.get("chapter"))
            if chapter is not None:
                score += self._recency_score(current_chapter, chapter)
                reasons.append("recency")

            overlap = query_terms.intersection(self._terms(document + " " + " ".join(str(v) for v in metadata.values())))
            if overlap:
                score += min(8.0, len(overlap) * 2.0)
                reasons.append("query")

            metadata_entities = set(str(metadata.get("entities", "")).split(",")) | {str(metadata.get("character_id", ""))}
            metadata_entities.discard("")
            if entities.intersection(metadata_entities):
                score += 7.0
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
        entities = entities or set()
        query_terms = self._terms(query)
        ranked: list[RankedMemory] = []
        for card in cards:
            score = float(card.importance)
            reasons: list[str] = ["importance"]

            score += self.TYPE_WEIGHTS.get(card.type, 0.0)
            if card.type in self.TYPE_WEIGHTS:
                reasons.append(f"type:{card.type}")

            score += self._recency_score(current_chapter, card.chapter)
            reasons.append("recency")

            if entities.intersection(card.entities):
                score += 7.0
                reasons.append("entity")

            overlap = query_terms.intersection(self._terms(card.content + " " + " ".join(card.tags)))
            if overlap:
                score += min(8.0, len(overlap) * 2.0)
                reasons.append("query")

            if card.last_seen_chapter and card.last_seen_chapter < current_chapter:
                score += max(0.0, 2.0 - ((current_chapter - card.last_seen_chapter) / 100.0))
                reasons.append("last_seen")

            ranked.append(RankedMemory(card, score, tuple(reasons)))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _recency_score(self, current_chapter: int, item_chapter: int) -> float:
        if item_chapter > current_chapter:
            return -4.0
        distance = max(0, current_chapter - item_chapter)
        return max(0.0, 5.0 - (distance / 20.0))

    def _terms(self, text: str) -> set[str]:
        return {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", text)}

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
