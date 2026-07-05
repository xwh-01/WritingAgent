"""Continuity auditor focused on long-form consistency risks."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import ChapterOutline, ContinuityAuditReport, ContinuityIssue, Story


class ContinuityAuditorAgent(BaseAgent):
    name = "continuity_auditor"

    def audit_chapter(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        longform_context: str = "",
    ) -> ContinuityAuditReport:
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
            f"story_bible={story.story_bible.model_dump_json()}\n"
            f"pending_foreshadowing={json.dumps([f.model_dump() for f in story.foreshadowings if f.status == 'pending'], ensure_ascii=False)}\n"
            f"character_states={json.dumps(story.character_states, default=str, ensure_ascii=False)}\n"
            f"longform_context={longform_context[:6000]}\n"
            f"content={content[:12000]}"
        )
        try:
            report = self._parse_model(self._chat(system, user), ContinuityAuditReport)
            report.chapter_index = chapter_index
            report.risk_score = self._clamp(report.risk_score)
            report.passed = report.risk_score < 7.0 and not any(issue.severity == "high" for issue in report.issues)
            return report
        except Exception:
            return self._rule_audit(story, chapter_index, content, outline)

    def _rule_audit(
        self,
        story: Story,
        chapter_index: int,
        content: str,
        outline: ChapterOutline | None,
    ) -> ContinuityAuditReport:
        issues: list[ContinuityIssue] = []
        checked = list(story.story_bible.continuity_constraints[:20])

        for item in story.foreshadowings:
            if item.status == "pending" and item.target_chapter is not None and item.target_chapter <= chapter_index:
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
            if any(term in constraint.lower() for term in ("injury", "secret", "foreshadowing", "ability")):
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

        for character_id, states in story.character_states.items():
            previous = max((state for state in states if state.chapter < chapter_index), key=lambda item: item.chapter, default=None)
            current = max((state for state in states if state.chapter == chapter_index), key=lambda item: item.chapter, default=None)
            if previous and current and previous.location and current.location and previous.location != current.location:
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
            summary="No major continuity risks found." if not issues else f"Found {len(issues)} continuity risk(s).",
        )

    def _important_terms(self, text: str) -> list[str]:
        raw = [item.strip("，。,.!?;:()[]{}\"'") for item in text.split()]
        terms = [item.lower() for item in raw if len(item) >= 3]
        if terms:
            return terms
        return [char for char in text if "\u4e00" <= char <= "\u9fff"][:8]

    def _clamp(self, value: float) -> float:
        return max(0.0, min(10.0, float(value)))
