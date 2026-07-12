"""Cross-chapter character arc consistency auditor."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.core.models import (
    Character,
    CharacterContinuityIssue,
    CharacterContinuityReport,
    CharacterState,
    Story,
)
from novelforge.longform.character_state import CharacterStateTracker


class CharacterArcAuditorAgent(BaseAgent):
    """审计单个角色在一段章节范围内的人设和状态演变。"""

    name = "character_arc_auditor"

    def audit(
        self,
        story: Story,
        character: Character,
        start_chapter: int,
        end_chapter: int,
    ) -> CharacterContinuityReport:
        states = [
            state for state in story.memory.states.get(character.id, [])
            if start_chapter <= state.chapter <= end_chapter
        ]
        states.sort(key=lambda item: item.chapter)
        excerpts = []
        for chapter_index in range(start_chapter, end_chapter + 1):
            chapter = story.content.chapters.get(chapter_index)
            if chapter and chapter.content:
                excerpts.append({"chapter": chapter_index, "content": chapter.content[:3000]})
        payload = {
            "marker": "character_arc_audit",
            "character": character.model_dump(),
            "chapter_range": [start_chapter, end_chapter],
            "states": [state.model_dump() for state in states],
            "confirmed_facts": [
                fact.model_dump() for fact in story.memory.facts
                if fact.character_id == character.id and fact.user_confirmed
            ],
            "chapter_excerpts": excerpts,
            "output_schema": CharacterContinuityReport.model_json_schema(),
        }
        system = (
            "You audit a character arc across novel chapters. Flag only evidence-backed persona, knowledge, "
            "location, emotional, goal, or relationship discontinuities. Do not mistake deliberate development "
            "for a contradiction when a transition is present. Return strict CharacterContinuityReport JSON."
        )
        try:
            report = self._parse_model(
                self._chat(system, json.dumps(payload, ensure_ascii=False)), CharacterContinuityReport
            )
            report.character_id = character.id
            report.character_name = character.name
            report.start_chapter = start_chapter
            report.end_chapter = end_chapter
            report.trajectory = states
            report.affected_chapters = sorted({issue.chapter_index for issue in report.issues})
            report.passed = not any(issue.severity == "high" for issue in report.issues)
            return report
        except Exception:
            return self._rule_audit(character, states, start_chapter, end_chapter)

    def _rule_audit(
        self,
        character: Character,
        states: list[CharacterState],
        start_chapter: int,
        end_chapter: int,
    ) -> CharacterContinuityReport:
        tracker = CharacterStateTracker()
        issues: list[CharacterContinuityIssue] = []
        for previous, current in zip(states, states[1:], strict=False):
            for message in tracker.check_consistency(previous, current):
                dimension = "character_state"
                if "情绪" in message:
                    dimension = "emotion"
                elif "位置" in message:
                    dimension = "location"
                elif "记录" in message:
                    dimension = "knowledge"
                issues.append(CharacterContinuityIssue(
                    chapter_index=current.chapter,
                    previous_chapter=previous.chapter,
                    dimension=dimension,
                    severity="medium",
                    description=message,
                    evidence=(
                        f"第{previous.chapter}章: {previous.model_dump_json()}\n"
                        f"第{current.chapter}章: {current.model_dump_json()}"
                    ),
                    suggestion="补充可见的心理、行动或信息过渡，并保持既有事实。",
                ))
        affected = sorted({issue.chapter_index for issue in issues})
        return CharacterContinuityReport(
            character_id=character.id,
            character_name=character.name,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            trajectory=states,
            issues=issues,
            affected_chapters=affected,
            passed=not issues,
            summary=(
                "未发现基于状态记录的明显角色连续性问题。"
                if not issues else f"发现 {len(issues)} 个需要补过渡或修订的角色连续性问题。"
            ),
        )
