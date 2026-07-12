"""Small, explicit mutation services for the four Story aggregate domains."""

from __future__ import annotations

from novelforge.core.models import (
    AgentTraceRun,
    AutonomousRunReport,
    BatchWriteReport,
    Chapter,
    ChapterContract,
    CharacterFact,
    RevisionProposal,
    Story,
)


class ContentService:
    """Owns creative source material: outlines, contracts, chapters, and versions."""

    def set_outlines(self, story: Story, outlines: list) -> None:
        story.content.outlines = outlines

    def save_chapter(self, story: Story, chapter: Chapter) -> Chapter:
        story.content.chapters[chapter.index] = chapter
        story.current_chapter = chapter.index
        return chapter

    def save_contract(self, story: Story, contract: ChapterContract) -> ChapterContract:
        story.content.chapter_contracts[contract.chapter_index] = contract
        return contract


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


class QualityService:
    """Owns diagnostics, review artifacts, and approval-gated revision proposals."""

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
