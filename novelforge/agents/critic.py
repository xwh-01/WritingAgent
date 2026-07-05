"""Critic agent for continuity and craft review."""

from __future__ import annotations

import json
from typing import Any

from novelforge.agents.base import BaseAgent
from novelforge.core.models import ChapterOutline, Character, QualityReviewReport, ReviewReport, Story


class CriticAgent(BaseAgent):
    name = "critic"

    def review_chapter(
        self,
        chapter_content: str,
        chapter_outline: ChapterOutline,
        character_list: list[Character],
        plot_memory: list[dict[str, Any]] | str,
        longform_context: str = "",
    ) -> ReviewReport:
        system = (
            "你是专业小说编辑，检查逻辑漏洞、人设不一致、节奏问题并给修改建议。"
            "请严格输出 ReviewReport JSON: "
            "{logic_issues:list[str],character_issues:list[str],pacing_issues:list[str],"
            "suggestions:list[str],verdict:str}。"
        )
        user = (
            "审查报告 ReviewReport。\n"
            f"章节大纲: {json.dumps(chapter_outline.model_dump(), ensure_ascii=False)}\n"
            f"角色: {json.dumps([c.model_dump() for c in character_list], ensure_ascii=False)}\n"
            f"情节记忆: {json.dumps(plot_memory, ensure_ascii=False) if not isinstance(plot_memory, str) else plot_memory}\n"
            f"长篇一致性信息: {longform_context}\n"
            f"正文: {chapter_content[:12000]}\n只输出 JSON。"
        )
        try:
            return self._parse_model(self._chat(system, user), ReviewReport)
        except Exception:
            return ReviewReport(
                pacing_issues=["未能解析模型审查结果，请人工复核。"],
                suggestions=["检查章节目标、冲突升级和结尾钩子是否清晰。"],
            )

    def review_quality_scorecard(
        self,
        content: str,
        chapter_outline: ChapterOutline,
        story: Story,
        extra_context: str = "",
    ) -> QualityReviewReport:
        system = (
            "你是专业小说审查员。基于章节内容、大纲和故事全局状态，评估质量并严格输出 JSON。\n"
            "JSON 格式：{\n"
            '  "scores": {\n'
            '    "logic_consistency": 1-10,\n'
            '    "character_fidelity": 1-10,\n'
            '    "foreshadowing_handling": 1-10,\n'
            '    "pacing": 1-10,\n'
            '    "style_uniformity": 1-10\n'
            "  },\n"
            '  "issues": [\n'
            '    {"dimension": "逻辑/人设/伏笔/节奏/风格", "severity": "high/medium/low", "description": "具体问题描述"}\n'
            "  ],\n"
            '  "overall_comment": "简短总评"\n'
            "}\n"
            "只输出 JSON，不要解释。"
        )
        user = (
            "quality_scorecard_review\n"
            f"章节大纲: {json.dumps(chapter_outline.model_dump(), ensure_ascii=False)}\n"
            f"章节内容: {content[:12000]}\n"
            f"故事全局记忆: {self._get_memory_snapshot(story)}\n"
            f"额外审查上下文: {extra_context[:4000]}"
        )
        try:
            report = self._parse_model(self._chat(system, user), QualityReviewReport)
            report.scores.logic_consistency = self._clamp(report.scores.logic_consistency)
            report.scores.character_fidelity = self._clamp(report.scores.character_fidelity)
            report.scores.foreshadowing_handling = self._clamp(report.scores.foreshadowing_handling)
            report.scores.pacing = self._clamp(report.scores.pacing)
            report.scores.style_uniformity = self._clamp(report.scores.style_uniformity)
            return report
        except Exception:
            return self._fallback_quality_review(content, chapter_outline, story)

    def _get_memory_snapshot(self, story: Story) -> str:
        pending_foreshadowings = [item.model_dump() for item in story.foreshadowings if item.status == "pending"][-10:]
        recent_events = [item.model_dump() for item in sorted(story.causal_events, key=lambda event: event.chapter)[-12:]]
        latest_states = {}
        for character_id, states in story.character_states.items():
            if states:
                latest = max(states, key=lambda item: item.chapter)
                character = story.characters.get(character_id)
                latest_states[character.name if character else character_id] = latest.model_dump()
        recent_summaries = [
            item.model_dump()
            for _, item in sorted(story.chapter_summaries.items(), key=lambda pair: pair[0])[-5:]
        ]
        snapshot = {
            "premise": story.premise,
            "style_guide": story.style_guide,
            "pending_foreshadowings": pending_foreshadowings,
            "recent_causal_events": recent_events,
            "latest_character_states": latest_states,
            "recent_chapter_summaries": recent_summaries,
        }
        return json.dumps(snapshot, ensure_ascii=False)

    def _fallback_quality_review(self, content: str, chapter_outline: ChapterOutline, story: Story) -> QualityReviewReport:
        from novelforge.core.models import QualityScores, RevisionIssue

        issues: list[RevisionIssue] = []
        scores = QualityScores(
            logic_consistency=8.0,
            character_fidelity=8.0,
            foreshadowing_handling=8.0,
            pacing=8.0,
            style_uniformity=8.0,
        )
        if len(content.strip()) < 300:
            scores.pacing = 6.0
            issues.append(RevisionIssue(dimension="节奏", severity="medium", description="章节篇幅偏短，情节推进和场景层次可能不足。"))
        if chapter_outline.conflict and not any(token in content for token in ("冲突", "选择", "危险", "代价", "阻力", "失败")):
            scores.logic_consistency = 6.5
            issues.append(RevisionIssue(dimension="逻辑", severity="medium", description="正文没有充分体现章节大纲中的核心冲突。"))
        pending_due = [
            item
            for item in story.foreshadowings
            if item.status == "pending" and item.target_chapter is not None and item.target_chapter <= chapter_outline.chapter_index
        ]
        if pending_due:
            scores.foreshadowing_handling = 6.0
            issues.append(RevisionIssue(dimension="伏笔", severity="high", description="存在计划回收但尚未处理的伏笔。"))
        if story.style_guide and not any(word in content for word in story.style_guide.split()[:3]):
            scores.style_uniformity = 7.0
        return QualityReviewReport(scores=scores, issues=issues, overall_comment="规则兜底审查完成。")

    def _clamp(self, value: float) -> float:
        return max(1.0, min(10.0, float(value)))
