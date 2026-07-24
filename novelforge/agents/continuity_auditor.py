"""Continuity auditor focused on long-form consistency risks."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.domain import Chapter, ChapterOutline, ContinuityAuditReport, ContinuityIssue, Story


class ContinuityAuditorAgent(BaseAgent):
    """连续性审计 Agent，检查长篇小说的长期一致性风险。"""

    name = "continuity_auditor"

    def audit_chapter(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        longform_context: str = "",
    ) -> ContinuityAuditReport:
        """审计章节的连续性风险：伏笔、因果关系、人物状态、设定一致性与章节目标。"""
        outline = None
        try:
            outline = story.get_outline(chapter_index)
        except KeyError:
            outline = None

        system = (
            "You are a continuity auditor for a long novel. Check only long-form consistency risks: "
            "story bible violations, character-state contradictions, foreshadowing overdue or ignored, "
            "causal gaps, location/time jumps, ability/rule drift, and chapter-goal mismatch. "
            "Return strict JSON matching ContinuityAuditReport."
        )
        user = (
            "continuity_audit\n"
            f"chapter={chapter_index}\n"
            f"outline={outline.model_dump_json() if outline else '{}'}\n"
            f"story_bible={story.knowledge.guide.model_dump_json()}\n"
            f"pending_foreshadowing={json.dumps([f.model_dump() for f in story.knowledge.foreshadowings if f.status == 'pending'], ensure_ascii=False)}\n"
            f"character_states={json.dumps(story.knowledge.character_states, default=str, ensure_ascii=False)}\n"
            f"longform_context={longform_context[:6000]}\n"
            f"content={content[:12000]}"
        )
        try:
            report = self._chat_model(system, user, ContinuityAuditReport)
            report.chapter_index = chapter_index
            report.risk_score = self._clamp(report.risk_score)
            report.passed = report.risk_score < 7.0 and not any(
                issue.severity == "high" for issue in report.issues
            )
            report.audit_method = "llm"
            return report
        except Exception:
            report = self._rule_audit(story, chapter_index, content, outline)
            report.audit_method = "rule_fallback"
            return report

    def audit_local_patch(
        self,
        story: Story,
        candidate: Chapter,
        changed_scene_indexes: list[int],
        longform_context: str = "",
    ) -> ContinuityAuditReport:
        """Audit only a changed scene and its hand-off neighbours after a patch.

        Full chapter review is intentionally avoided here: the unchanged scenes
        were already reviewed, while the mutation boundaries are where state,
        knowledge, location, and temporal regressions can be introduced.
        """
        changed = sorted(set(changed_scene_indexes))
        window = {
            scene.scene_index
            for scene in candidate.beats
            if any(abs(scene.scene_index - item) <= 1 for item in changed)
        }
        scenes = [item for item in sorted(candidate.beats, key=lambda item: item.scene_index) if item.scene_index in window]
        content = "\n\n--- scene boundary ---\n\n".join(
            f"[scene {item.scene_index}; changed={item.scene_index in changed}; end_state={json.dumps(item.end_state, ensure_ascii=False)}]\n{item.content}"
            for item in scenes
        )
        system = (
            "You are a local continuity auditor for a patched novel scene. Check only the changed scene and "
            "its neighbours for direct contradictions in state hand-off, character knowledge, location, time, "
            "items, decisions, promises, and chapter facts. Return strict ContinuityAuditReport JSON. Mark a "
            "high issue only when you can cite a direct contradiction."
        )
        user = (
            "continuity_patch_audit\n"
            f"chapter={candidate.index}\nchanged_scenes={changed}\n"
            f"story_bible={story.knowledge.guide.model_dump_json()}\n"
            f"longform_context={longform_context[:3500]}\n"
            f"scene_window={content[:12000]}"
        )
        try:
            report = self._chat_model(system, user, ContinuityAuditReport, temperature=0.1, max_tokens=1000)
            report.chapter_index = candidate.index
            report.risk_score = self._clamp(report.risk_score)
            report.passed = report.risk_score < 7.0 and not any(
                issue.severity == "high" for issue in report.issues
            )
            report.audit_method = "local_patch"
            return report
        except Exception:
            report = self._rule_audit(story, candidate.index, content, None)
            report.audit_method = "local_patch_rule_fallback"
            return report

    def _rule_audit(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        outline: ChapterOutline | None,
    ) -> ContinuityAuditReport:
        """基于规则的连续性审计兜底：检查伏笔到期、冲突体现、约束遵守、位置跳变。"""
        issues: list[ContinuityIssue] = []
        checked = list(story.knowledge.guide.continuity_constraints[:20])

        for item in story.knowledge.foreshadowings:
            if (
                item.status == "pending"
                and item.target_chapter is not None
                and item.target_chapter <= chapter_index
            ):
                issues.append(
                    ContinuityIssue(
                        dimension="foreshadowing",
                        severity="high",
                        description=f"Foreshadowing {item.id} is due by chapter {item.target_chapter} but still pending.",
                        evidence=item.description,
                        suggestion="Resolve it, explicitly delay it, or update its target chapter.",
                    )
                )

        if outline and outline.conflict:
            conflict_terms = self._important_terms(outline.conflict)
            if conflict_terms and not any(term in content for term in conflict_terms):
                issues.append(
                    ContinuityIssue(
                        dimension="chapter_goal",
                        severity="medium",
                        description="Chapter content may not address the planned conflict.",
                        evidence=outline.conflict,
                        suggestion="Make the chapter's central scene visibly engage the outline conflict.",
                    )
                )

        for constraint in checked:
            tokens = self._important_terms(constraint)
            if any(
                term in constraint.lower()
                for term in ("injury", "secret", "foreshadowing", "ability")
            ):
                if tokens and not any(term in content.lower() for term in tokens[:4]):
                    issues.append(
                        ContinuityIssue(
                            dimension="story_bible",
                            severity="medium",
                            description="A continuity constraint may be unacknowledged in this chapter.",
                            evidence=constraint,
                            suggestion="Mention, preserve, or deliberately update the constraint.",
                        )
                    )

        for character_id, states in story.knowledge.character_states.items():
            previous = max(
                (state for state in states if state.chapter < chapter_index),
                key=lambda item: item.chapter,
                default=None,
            )
            current = max(
                (state for state in states if state.chapter == chapter_index),
                key=lambda item: item.chapter,
                default=None,
            )
            if (
                previous
                and current
                and previous.location
                and current.location
                and previous.location != current.location
            ):
                if not current.knowledge_gained:
                    issues.append(
                        ContinuityIssue(
                            dimension="character_state",
                            severity="low",
                            description=f"{character_id} changes location without a clear transition note.",
                            evidence=f"{previous.location} -> {current.location}",
                            suggestion="Add a transition beat or travel explanation.",
                        )
                    )

        severity_weight = {"low": 1.5, "medium": 3.0, "high": 5.0}
        risk = min(10.0, sum(severity_weight.get(issue.severity, 2.0) for issue in issues))
        return ContinuityAuditReport(
            chapter_index=chapter_index,
            risk_score=risk,
            passed=risk < 7.0 and not any(issue.severity == "high" for issue in issues),
            issues=issues,
            checked_constraints=checked,
            summary=(
                "No major continuity risks found."
                if not issues
                else f"Found {len(issues)} continuity risk(s)."
            ),
            audit_method="rule",
        )

    def _important_terms(self, text: str) -> list[str]:
        """提取文本中的重要词汇（≥3 个字符的词或中文字符）。"""
        raw = [item.strip("，。,.!?;:()[]{}\"'") for item in text.split()]
        terms = [item.lower() for item in raw if len(item) >= 3]
        if terms:
            return terms
        return [char for char in text if "\u4e00" <= char <= "\u9fff"][:8]

    def _clamp(self, value: float) -> float:
        """将分数钳制在 0.0 到 10.0 范围内。"""
        return max(0.0, min(10.0, float(value)))
