"""Small, explicit mutation services for the four Story aggregate domains."""

from __future__ import annotations

from novelforge.core.models import (
    AgentTraceRun,
    AutoRevisionReport,
    AutonomousRunReport,
    BatchWriteReport,
    Chapter,
    ChapterContract,
    ChapterOutline,
    CharacterContinuityReport,
    CharacterFact,
    CharacterState,
    ContinuityAuditReport,
    MemoryCard,
    RevisionProposal,
    Story,
)


class ContentService:
    """Owns creative source material: outlines, contracts, chapters, and versions."""

    def set_outlines(self, story: Story, outlines: list) -> None:
        story.content.outlines = outlines

    def append_outlines(self, story: Story, outlines: list[ChapterOutline]) -> None:
        story.content.outlines.extend(outlines)

    def save_chapter(self, story: Story, chapter: Chapter) -> Chapter:
        story.content.chapters[chapter.index] = chapter
        story.current_chapter = chapter.index
        return chapter

    def save_contract(self, story: Story, contract: ChapterContract) -> ChapterContract:
        story.content.chapter_contracts[contract.chapter_index] = contract
        return contract

    def get_chapter(self, story: Story, chapter_index: int) -> Chapter | None:
        return story.content.chapters.get(chapter_index)

    def set_chapter(self, story: Story, chapter_index: int, chapter: Chapter) -> None:
        story.content.chapters[chapter_index] = chapter

    def add_character(self, story: Story, character) -> None:
        story.content.characters[character.id] = character

    def add_world_setting(self, story: Story, setting) -> None:
        story.content.world_settings.append(setting)


class MemoryService:
    """Owns durable facts and long-form recall state."""

    def set_facts(self, story: Story, facts: list[CharacterFact]) -> None:
        story.memory.facts = facts

    def add_fact(self, story: Story, fact: CharacterFact) -> CharacterFact:
        story.memory.facts = [item for item in story.memory.facts if item.id != fact.id]
        story.memory.facts.append(fact)
        return fact

    def confirm_fact(self, story: Story, fact: CharacterFact, ledger) -> CharacterFact:
        """Apply the fact ledger's precedence rules through the memory ownership boundary."""
        return ledger.upsert_confirmed(story, fact)

    def remove_confirmed_fact(self, story: Story, fact_id: str, ledger) -> bool:
        return ledger.delete_confirmed(story, fact_id)

    def save_states(self, story: Story, states: dict[str, list[CharacterState]]) -> None:
        story.memory.states = states

    def update_character_state(self, story: Story, character_id: str, states: list[CharacterState]) -> None:
        story.memory.states[character_id] = states

    def save_memory_cards(self, story: Story, cards: list[MemoryCard]) -> None:
        story.memory.cards = cards

    def save_chapter_summary(self, story: Story, chapter_index: int, summary) -> None:
        story.memory.chapter_summaries[chapter_index] = summary

    def save_chapter_summaries(self, story: Story, summaries: dict) -> None:
        story.memory.chapter_summaries = summaries

    def save_volume_summaries(self, story: Story, summaries: list) -> None:
        story.memory.volume_summaries = summaries

    def save_arc_summaries(self, story: Story, summaries: list) -> None:
        story.memory.arc_summaries = summaries

    def add_foreshadowing(self, story: Story, foreshadowing) -> None:
        story.memory.foreshadowings.append(foreshadowing)

    def add_causal_event(self, story: Story, event) -> None:
        story.memory.causal_events.append(event)

    def set_causal_events(self, story: Story, events: list) -> None:
        story.memory.causal_events = events

    def update_story_bible_constraint(self, story: Story, constraint: str) -> None:
        if constraint not in story.memory.story_bible.continuity_constraints:
            story.memory.story_bible.continuity_constraints.append(constraint)


class QualityService:
    """Owns diagnostics, review artifacts, and approval-gated revision proposals."""

    def save_auto_revision_report(self, story: Story, chapter_index: int, report: AutoRevisionReport) -> None:
        story.quality.auto_revision_reports[chapter_index] = report

    def save_continuity_report(self, story: Story, chapter_index: int, report: ContinuityAuditReport) -> None:
        story.quality.continuity_reports[chapter_index] = report

    def save_character_continuity_report(self, story: Story, report: CharacterContinuityReport) -> None:
        story.quality.character_continuity_reports = [
            item for item in story.quality.character_continuity_reports
            if not (
                item.character_id == report.character_id
                and item.start_chapter == report.start_chapter
                and item.end_chapter == report.end_chapter
            )
        ]
        story.quality.character_continuity_reports.append(report)

    def add_proposal(self, story: Story, proposal: RevisionProposal) -> RevisionProposal:
        story.quality.revision_proposals.append(proposal)
        return proposal

    def get_proposal(self, story: Story, proposal_id: str) -> RevisionProposal | None:
        return next((item for item in story.quality.revision_proposals if item.id == proposal_id), None)


class AgentRunService:
    """Owns persistent Director, autonomous, and batch execution records."""

    def add_director_run(self, story: Story, run: AgentTraceRun) -> AgentTraceRun:
        story.agent_runs.director.append(run)
        return run

    def add_autonomous_run(self, story: Story, run: AutonomousRunReport) -> AutonomousRunReport:
        story.agent_runs.autonomous.append(run)
        return run

    def add_batch_report(self, story: Story, report: BatchWriteReport) -> BatchWriteReport:
        story.agent_runs.batch_reports.append(report)
        return report

    def get_director_run(self, story: Story, run_id: str) -> AgentTraceRun | None:
        return next((run for run in story.agent_runs.director if run.id == run_id), None)
