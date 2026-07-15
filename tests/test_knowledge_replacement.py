from __future__ import annotations

import pytest

from novelforge.domain import (
    Chapter,
    ChapterSummary,
    KnowledgeSource,
    Story,
    TimelineEvent,
    content_digest,
)
from novelforge.longform.knowledge_pipeline import ChapterKnowledgePipeline


class ReplacingProcessor:
    def process_new_chapter(self, story, chapter_index, content):
        story.knowledge.chapter_summaries[chapter_index] = ChapterSummary(
            chapter_index=chapter_index,
            chapter_summary="new summary",
        )
        story.knowledge.timeline.append(
            TimelineEvent(id="new-event", chapter=chapter_index, description="New event")
        )
        return {"pacing": {}, "pacing_warning": "", "extraction": None}


class FailingProcessor:
    def process_new_chapter(self, story, chapter_index, content):
        story.knowledge.chapter_summaries[chapter_index] = ChapterSummary(
            chapter_index=chapter_index,
            chapter_summary="partial mutation",
        )
        raise RuntimeError("extraction failed")


def story_with_rewritten_chapter() -> Story:
    story = Story(title="Rewrite", premise="A rewrite test.")
    chapter = Chapter(index=1, title="One", content="New version", version=2)
    story.manuscript.chapters[1] = chapter
    story.knowledge.sources[1] = KnowledgeSource(
        chapter_index=1,
        manuscript_version=1,
        content_digest=content_digest("Old version"),
    )
    story.knowledge.chapter_summaries[1] = ChapterSummary(
        chapter_index=1,
        chapter_summary="old summary",
    )
    story.knowledge.timeline = [TimelineEvent(id="old-event", chapter=1, description="Old event")]
    return story


def test_reprocessing_replaces_one_chapter_projection() -> None:
    story = story_with_rewritten_chapter()
    chapter = story.require_chapter(1)

    ChapterKnowledgePipeline(ReplacingProcessor()).process(story, chapter)

    assert story.knowledge.chapter_summaries[1].chapter_summary == "new summary"
    assert [item.id for item in story.knowledge.timeline] == ["new-event"]
    assert story.knowledge.sources[1].manuscript_version == 2
    story.assert_consistent()


def test_failed_extraction_cannot_leak_partial_knowledge() -> None:
    story = story_with_rewritten_chapter()
    original = story.knowledge.model_dump_json()

    with pytest.raises(RuntimeError, match="extraction failed"):
        ChapterKnowledgePipeline(FailingProcessor()).process(story, story.require_chapter(1))

    assert story.knowledge.model_dump_json() == original
