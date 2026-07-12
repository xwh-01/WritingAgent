"""Prepare Story data for dashboard visualization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novelforge.core.models import Chapter, Story


@dataclass
class DashboardData:
    """仪表盘汇总数据容器，包含伏笔、角色时间线、节奏热力图等可视化数据。"""

    foreshadowings: list[dict[str, Any]]
    character_timeline: dict[str, list[dict[str, Any]]]
    pacing_heatmap: list[dict[str, Any]]
    quality_trend: list[dict[str, Any]]
    causality_graph: dict[str, list[dict[str, Any]]]
    story_overview: dict[str, Any]


class DashboardDataProvider:
    """从 Story 实例中提取并整理所有仪表盘可视化所需数据。"""

    def __init__(self, story: Story):
        self.story = story

    def get_all_data(self) -> DashboardData:
        """汇集所有仪表盘数据并返回统一的 DashboardData 对象。"""
        return DashboardData(
            foreshadowings=self._prepare_foreshadowings(),
            character_timeline=self._prepare_character_timeline(),
            pacing_heatmap=self._prepare_pacing_heatmap(),
            quality_trend=self._prepare_quality_trend(),
            causality_graph=self._prepare_causality_graph(),
            story_overview=self._prepare_story_overview(),
        )

    def _prepare_foreshadowings(self) -> list[dict[str, Any]]:
        """整理伏笔列表，标记过期（overdue）状态的伏笔。"""
        results: list[dict[str, Any]] = []
        current_chapter = self.story.current_chapter
        for item in self.story.memory.foreshadowings:
            status = item.status
            if item.status == "pending" and item.target_chapter and current_chapter > item.target_chapter:
                status = "overdue"
            results.append(
                {
                    "id": item.id,
                    "description": item.description,
                    "created_chapter": item.created_chapter,
                    "target_chapter": item.target_chapter,
                    "status": status,
                    "notes": item.notes,
                }
            )
        return results

    def _prepare_character_timeline(self) -> dict[str, list[dict[str, Any]]]:
        """构建角色状态时间线，以角色名为键，按章节排列状态快照。"""
        timeline: dict[str, list[dict[str, Any]]] = {}
        for character_id, states in self.story.memory.states.items():
            character = self.story.content.characters.get(character_id)
            name = character.name if character else character_id
            timeline[name] = [
                {
                    "chapter": state.chapter,
                    "emotion": state.emotional_state,
                    "location": state.location,
                    "knowledge": state.knowledge_gained,
                    "relationship_changes": state.relationship_changes,
                }
                for state in sorted(states, key=lambda item: item.chapter)
            ]
        return timeline

    def _prepare_pacing_heatmap(self) -> list[dict[str, Any]]:
        """生成章节节奏热力图数据，包含冲突强度、对话/动作比例等指标。"""
        heatmap: list[dict[str, Any]] = []
        for index, chapter in sorted(self.story.content.chapters.items()):
            summary = self.story.memory.chapter_summaries.get(index)
            scene_count = len(summary.scene_summaries) if summary else max(len(chapter.beats), 1)
            content_len = len(chapter.content or "")
            dialogue_ratio = self._estimate_dialogue_ratio(chapter.content)
            action_ratio = self._estimate_action_ratio(chapter.content)
            heatmap.append(
                {
                    "chapter": index,
                    "title": chapter.title,
                    "conflict_intensity": self._estimate_conflict(chapter),
                    "dialogue_ratio": dialogue_ratio,
                    "action_ratio": action_ratio,
                    "scene_count": scene_count,
                    "word_count": content_len,
                    "status": chapter.status,
                }
            )
        return heatmap

    def _estimate_conflict(self, chapter: Chapter) -> int:
        """根据章节正文和纲要中的关键词估算冲突强度（1-10 分）。"""
        outline = next((item for item in self.story.content.outlines if item.chapter_index == chapter.index), None)
        high_keywords = ("战斗", "死亡", "背叛", "揭露", "决裂", "危机", "毁灭", "失败", "受伤")
        medium_keywords = ("争吵", "威胁", "秘密", "逃离", "对决", "真相", "选择", "冲突")
        text = f"{outline.conflict if outline else ''} {outline.summary if outline else ''} {chapter.content[:1200]}"
        score = 3
        score += sum(3 for keyword in high_keywords if keyword in text)
        score += sum(1 for keyword in medium_keywords if keyword in text)
        return max(1, min(score, 10))

    def _prepare_causality_graph(self) -> dict[str, list[dict[str, Any]]]:
        """构建因果事件图，生成节点列表和因果关系边列表。"""
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        known_ids = set()
        for event in self.story.memory.causal_events:
            known_ids.add(event.id)
            nodes.append(
                {
                    "id": event.id,
                    "label": event.description[:50],
                    "chapter": event.chapter,
                    "description": event.description,
                }
            )
        for event in self.story.memory.causal_events:
            for cause_id in event.causes:
                if cause_id in known_ids:
                    edges.append({"source": cause_id, "target": event.id, "relation": "causes"})
            for effect_id in event.effects:
                if effect_id in known_ids:
                    edges.append({"source": event.id, "target": effect_id, "relation": "leads_to"})
        unique_edges = {(edge["source"], edge["target"], edge["relation"]): edge for edge in edges}
        return {"nodes": nodes, "edges": list(unique_edges.values())}

    def _prepare_quality_trend(self) -> list[dict[str, Any]]:
        """聚合自动修订报告和连续性审计的评分趋势数据。"""
        trend: list[dict[str, Any]] = []
        for chapter_index, report in sorted(self.story.quality.auto_revision_reports.items()):
            for round_report in report.rounds:
                scores = round_report.review_report.scores
                trend.append(
                    {
                        "chapter": chapter_index,
                        "round": round_report.round,
                        "total_score": round_report.total_score,
                        "logic_consistency": scores.logic_consistency,
                        "character_fidelity": scores.character_fidelity,
                        "foreshadowing_handling": scores.foreshadowing_handling,
                        "pacing": scores.pacing,
                        "style_uniformity": scores.style_uniformity,
                        "passed": report.passed,
                    }
                )
            if report.final_score and not report.rounds:
                trend.append(
                    {
                        "chapter": chapter_index,
                        "round": 0,
                        "total_score": report.final_score,
                        "passed": report.passed,
                    }
                )
        reported_chapters = {item["chapter"] for item in trend}
        for chapter_index, report in sorted(self.story.quality.continuity_reports.items()):
            if chapter_index in reported_chapters:
                for item in trend:
                    if item["chapter"] == chapter_index:
                        item["continuity_risk"] = report.risk_score
                        item["continuity_passed"] = report.passed
                continue
            trend.append(
                {
                    "chapter": chapter_index,
                    "round": 0,
                    "total_score": max(0.0, 10.0 - report.risk_score),
                    "continuity_risk": report.risk_score,
                    "continuity_passed": report.passed,
                    "passed": report.passed,
                }
            )
        return trend

    def _prepare_story_overview(self) -> dict[str, Any]:
        """计算故事概览统计数据，包括完成率、角色数、伏笔状态等。"""
        completed = [chapter for chapter in self.story.content.chapters.values() if chapter.status in {"finalized", "published"}]
        revised = [chapter for chapter in self.story.content.chapters.values() if chapter.status == "revised"]
        pending_foreshadowings = [item for item in self._prepare_foreshadowings() if item["status"] == "pending"]
        overdue_foreshadowings = [item for item in self._prepare_foreshadowings() if item["status"] == "overdue"]
        return {
            "id": str(self.story.id),
            "title": self.story.title,
            "premise": self.story.premise,
            "genre": self.story.genre,
            "status": self.story.status,
            "total_chapters": len(self.story.content.outlines),
            "drafted_chapters": len(self.story.content.chapters),
            "completed_chapters": len(completed),
            "revised_chapters": len(revised),
            "current_chapter": self.story.current_chapter,
            "character_count": len(self.story.content.characters),
            "foreshadowing_pending": len(pending_foreshadowings),
            "foreshadowing_overdue": len(overdue_foreshadowings),
            "event_count": len(self.story.memory.causal_events),
            "summary_count": len(self.story.memory.chapter_summaries),
            "auto_report_count": len(self.story.quality.auto_revision_reports),
            "continuity_report_count": len(self.story.quality.continuity_reports),
            "continuity_risk_count": sum(1 for report in self.story.quality.continuity_reports.values() if not report.passed),
        }

    def _estimate_dialogue_ratio(self, content: str) -> float:
        """估算正文中的对话比例（0-100），基于引号行和冒号行占比。"""
        if not content:
            return 0.0
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return 0.0
        dialogue_lines = sum(1 for line in lines if line.startswith(("“", "\"", "「", "'")) or "：" in line or ":" in line)
        quote_density = (content.count("“") + content.count('"') + content.count("「")) / max(len(content), 1)
        return round(min(100.0, (dialogue_lines / len(lines) + quote_density) * 100), 1)

    def _estimate_action_ratio(self, content: str) -> float:
        """估算正文中的动作描写比例（0-100），基于动作关键词命中率。"""
        if not content:
            return 0.0
        action_words = ("冲", "跑", "扑", "射", "挡", "击", "推", "摔", "喊", "抢", "扑救", "追", "逃")
        hits = sum(content.count(word) for word in action_words)
        return round(min(100.0, hits / max(len(content), 1) * 300), 1)
