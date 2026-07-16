"""Small mutation services aligned one-to-one with Story aggregate domains."""

from __future__ import annotations

from novelforge.domain import (
    Chapter,
    ChapterContract,
    ChapterGenerationReport,
    ChapterOutline,
    ChapterStatus,
    Character,
    CharacterContinuityReport,
    CharacterFact,
    CharacterState,
    ContinuityAuditReport,
    RetrievalNote,
    ReviewReport,
    Story,
    WorldSetting,
)


class DesignService:
    """Owns creative intent: cast, world, outlines, and chapter contracts."""

    def set_outlines(self, story: Story, outlines: list) -> None:
        story.design.outlines = outlines

    def append_outlines(self, story: Story, outlines: list[ChapterOutline]) -> None:
        story.design.outlines.extend(outlines)

    def save_contract(self, story: Story, contract: ChapterContract) -> ChapterContract:
        story.design.chapter_contracts[contract.chapter_index] = contract
        return contract

    def add_character(self, story: Story, character: Character) -> None:
        story.design.characters[character.id] = character

    def add_world_setting(self, story: Story, setting: WorldSetting) -> None:
        story.design.world_settings = [
            item for item in story.design.world_settings if item.id != setting.id
        ]
        story.design.world_settings.append(setting)


class ManuscriptService:
    """Owns generated or user-edited chapter text and chapter versions."""

    def save_chapter(self, story: Story, chapter: Chapter) -> Chapter:
        story.manuscript.chapters[chapter.index] = chapter
        story.current_chapter = chapter.index
        return chapter

    def get_chapter(self, story: Story, chapter_index: int) -> Chapter | None:
        return story.manuscript.chapters.get(chapter_index)

    def set_chapter(self, story: Story, chapter_index: int, chapter: Chapter) -> None:
        story.manuscript.chapters[chapter_index] = chapter

    def commit_candidate(self, story: Story, candidate: Chapter) -> Chapter:
        """Promote one accepted candidate and preserve exactly one prior snapshot."""
        return self._promote(story, candidate, ChapterStatus.REVIEWED)

    def commit_user_edit(self, story: Story, candidate: Chapter) -> Chapter:
        """Commit explicit user-authored prose while retaining the requested status."""
        return self._promote(story, candidate, candidate.status)

    @staticmethod
    def _promote(
        story: Story,
        candidate: Chapter,
        status: ChapterStatus,
    ) -> Chapter:
        official = story.manuscript.chapters.get(candidate.index)
        committed = candidate.model_copy(deep=True)
        if official is None:
            committed.version = 1
            committed.history = []
        else:
            committed.version = official.version + 1
            committed.history = list(official.history)
            if official.content:
                committed.history.append(official.snapshot())
        committed.status = status
        story.manuscript.chapters[committed.index] = committed
        story.current_chapter = committed.index
        return committed


class KnowledgeService:
    """Own canonical knowledge derived from committed manuscript content."""

    def set_facts(self, story: Story, facts: list[CharacterFact]) -> None:
        story.knowledge.character_facts = facts

    def add_fact(self, story: Story, fact: CharacterFact) -> CharacterFact:
        story.knowledge.character_facts = [
            item for item in story.knowledge.character_facts if item.id != fact.id
        ]
        story.knowledge.character_facts.append(fact)
        return fact

    def confirm_fact(self, story: Story, fact: CharacterFact, ledger) -> CharacterFact:
        """Apply the fact ledger's precedence rules through the knowledge boundary."""
        return ledger.upsert_confirmed(story, fact)

    def remove_confirmed_fact(self, story: Story, fact_id: str, ledger) -> bool:
        return ledger.delete_confirmed(story, fact_id)

    def save_states(self, story: Story, states: dict[str, list[CharacterState]]) -> None:
        story.knowledge.character_states = states

    def update_character_state(
        self, story: Story, character_id: str, states: list[CharacterState]
    ) -> None:
        story.knowledge.character_states[character_id] = states

    def save_retrieval_notes(self, story: Story, notes: list[RetrievalNote]) -> None:
        story.knowledge.retrieval_notes = notes

    def save_chapter_summary(self, story: Story, chapter_index: int, summary) -> None:
        story.knowledge.chapter_summaries[chapter_index] = summary

    def save_chapter_summaries(self, story: Story, summaries: dict) -> None:
        story.knowledge.chapter_summaries = summaries

    def save_volume_summaries(self, story: Story, summaries: list) -> None:
        story.knowledge.volume_summaries = summaries

    def save_arc_summaries(self, story: Story, summaries: list) -> None:
        story.knowledge.arc_summaries = summaries

    def add_foreshadowing(self, story: Story, foreshadowing) -> None:
        story.knowledge.foreshadowings.append(foreshadowing)

    def add_timeline_event(self, story: Story, event) -> None:
        story.knowledge.timeline.append(event)

    def set_timeline(self, story: Story, events: list) -> None:
        story.knowledge.timeline = events


class QualityService:
    """Owns diagnostics, review artifacts, and approval-gated revision proposals."""

    def save_review_report(self, story: Story, chapter_index: int, report: ReviewReport) -> None:
        story.quality.review_reports[chapter_index] = report

    def invalidate_chapter_assessments(self, story: Story, chapter_index: int) -> None:
        """Remove canonical quality evidence tied to old prose."""
        story.quality.review_reports.pop(chapter_index, None)
        story.quality.continuity_reports.pop(chapter_index, None)
        story.quality.generation_reports.pop(chapter_index, None)

    def invalidate_story_assessments(self, story: Story) -> None:
        """Invalidate quality evidence after author-controlled canon changes."""
        story.quality.review_reports.clear()
        story.quality.continuity_reports.clear()
        story.quality.generation_reports.clear()
        story.quality.character_continuity_reports.clear()

    def save_generation_report(
        self,
        story: Story,
        report: ChapterGenerationReport,
    ) -> None:
        story.quality.generation_reports[report.chapter_index] = report

    def save_continuity_report(
        self, story: Story, chapter_index: int, report: ContinuityAuditReport
    ) -> None:
        story.quality.continuity_reports[chapter_index] = report

    def save_character_continuity_report(
        self, story: Story, report: CharacterContinuityReport
    ) -> None:
        story.quality.character_continuity_reports = [
            item
            for item in story.quality.character_continuity_reports
            if not (
                item.character_id == report.character_id
                and item.start_chapter == report.start_chapter
                and item.end_chapter == report.end_chapter
            )
        ]
        story.quality.character_continuity_reports.append(report)
