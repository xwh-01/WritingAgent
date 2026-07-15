from __future__ import annotations

import pytest

from novelforge.domain import (
    Beat,
    Chapter,
    ChapterSummary,
    CharacterObservation,
    KnowledgeSource,
    Story,
    content_digest,
)


def test_committed_prose_requires_exact_knowledge_provenance(planned_story: Story) -> None:
    chapter = Chapter(index=1, title="The Choice", content="Committed prose.")
    planned_story.manuscript.chapters[1] = chapter

    with pytest.raises(ValueError, match="no knowledge provenance"):
        planned_story.assert_consistent()

    planned_story.knowledge.sources[1] = KnowledgeSource(
        chapter_index=1,
        manuscript_version=chapter.version,
        content_digest=content_digest(chapter.content),
    )
    planned_story.assert_consistent()

    chapter.content = "Changed without reprocessing."
    with pytest.raises(ValueError, match="digest"):
        planned_story.assert_consistent()


def test_generation_view_hides_current_and_future_prose(planned_story: Story) -> None:
    planned_story.design.outlines.append(
        planned_story.design.outlines[0].model_copy(update={"chapter_index": 2, "title": "Later"})
    )
    first = Chapter(
        index=1,
        title="The Choice",
        content="Old official prose.",
        beats=[Beat(scene_index=1, goal="Choose", obstacle="Fear", outcome="Choice")],
    )
    second = Chapter(index=2, title="Later", content="Future prose.")
    planned_story.manuscript.chapters = {1: first, 2: second}
    for chapter in (first, second):
        planned_story.knowledge.sources[chapter.index] = KnowledgeSource(
            chapter_index=chapter.index,
            manuscript_version=chapter.version,
            content_digest=content_digest(chapter.content),
        )
        planned_story.knowledge.chapter_summaries[chapter.index] = ChapterSummary(
            chapter_index=chapter.index,
            chapter_summary=chapter.content,
        )
    planned_story.knowledge.character_observations.append(
        CharacterObservation(
            character_id="future",
            name="Future Character",
            source_chapter=2,
        )
    )

    view = planned_story.generation_view(1)

    assert view.manuscript.chapters[1].content == ""
    assert view.manuscript.chapters[1].beats
    assert 2 not in view.manuscript.chapters
    assert view.knowledge.sources == {}
    assert view.knowledge.chapter_summaries == {}
    assert view.knowledge.character_observations == []
