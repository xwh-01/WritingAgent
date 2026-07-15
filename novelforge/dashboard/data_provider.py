"""Read-only dashboard projection from one Story aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novelforge.domain import Story


@dataclass(frozen=True)
class DashboardData:
    foreshadowings: list[dict[str, Any]]
    character_timeline: dict[str, list[dict[str, Any]]]
    pacing_heatmap: list[dict[str, Any]]
    quality_trend: list[dict[str, Any]]
    causality_graph: dict[str, list[dict[str, Any]]]
    story_overview: dict[str, Any]


class DashboardDataProvider:
    def __init__(self, story: Story) -> None:
        self.story = story

    def get_all_data(self) -> DashboardData:
        return DashboardData(
            foreshadowings=self._foreshadowings(),
            character_timeline=self._character_timeline(),
            pacing_heatmap=self._chapter_metrics(),
            quality_trend=self._quality_trend(),
            causality_graph=self._causality_graph(),
            story_overview=self._overview(),
        )

    def _foreshadowings(self) -> list[dict[str, Any]]:
        result = []
        for item in self.story.knowledge.foreshadowings:
            data = item.model_dump()
            if (
                item.status == "pending"
                and item.target_chapter
                and self.story.current_chapter > item.target_chapter
            ):
                data["status"] = "overdue"
            result.append(data)
        return result

    def _character_timeline(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for character_id, states in self.story.knowledge.character_states.items():
            character = self.story.design.characters.get(character_id)
            key = character.name if character else character_id
            result[key] = [
                state.model_dump() for state in sorted(states, key=lambda item: item.chapter)
            ]
        return result

    def _chapter_metrics(self) -> list[dict[str, Any]]:
        return [
            {
                "chapter": index,
                "title": chapter.title,
                "character_count": len(chapter.content),
                "scene_count": len(chapter.beats),
                "status": chapter.status,
            }
            for index, chapter in sorted(self.story.manuscript.chapters.items())
        ]

    def _quality_trend(self) -> list[dict[str, Any]]:
        result = []
        for chapter_index, report in sorted(self.story.quality.generation_reports.items()):
            for attempt in report.attempts:
                result.append(
                    {
                        "chapter": chapter_index,
                        "attempt": attempt.attempt,
                        "total_score": attempt.score,
                        "decision": attempt.decision,
                        "passed": attempt.decision == "accept",
                        **attempt.quality.scores.model_dump(),
                    }
                )
        return result

    def _causality_graph(self) -> dict[str, list[dict[str, Any]]]:
        nodes = [
            {
                "id": event.id,
                "label": event.description[:50],
                "chapter": event.chapter,
                "description": event.description,
            }
            for event in self.story.knowledge.timeline
        ]
        known = {node["id"] for node in nodes}
        edges = []
        for event in self.story.knowledge.timeline:
            edges.extend(
                {"source": cause, "target": event.id, "relation": "causes"}
                for cause in event.causes
                if cause in known
            )
            edges.extend(
                {"source": event.id, "target": effect, "relation": "leads_to"}
                for effect in event.effects
                if effect in known
            )
        return {"nodes": nodes, "edges": edges}

    def _overview(self) -> dict[str, Any]:
        finalized = sum(
            chapter.status == "finalized" for chapter in self.story.manuscript.chapters.values()
        )
        return {
            "id": str(self.story.id),
            "title": self.story.title,
            "premise": self.story.premise,
            "genre": self.story.genre,
            "status": self.story.status,
            "total_chapters": len(self.story.design.outlines),
            "drafted_chapters": len(self.story.manuscript.chapters),
            "completed_chapters": finalized,
            "current_chapter": self.story.current_chapter,
            "character_count": len(self.story.design.characters),
            "event_count": len(self.story.knowledge.timeline),
            "summary_count": len(self.story.knowledge.chapter_summaries),
            "quality_report_count": len(self.story.quality.generation_reports),
            "continuity_report_count": len(self.story.quality.continuity_reports),
        }


__all__ = ["DashboardData", "DashboardDataProvider"]
