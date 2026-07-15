"""The single canonical-save then derived-index commit protocol."""

from __future__ import annotations

from dataclasses import dataclass

from novelforge.application.indexing import DerivedIndexService
from novelforge.domain import Story
from novelforge.storage.repository import StoryRepository


@dataclass(frozen=True)
class CommitResult:
    story: Story
    index_summary: dict[str, int | str] | None
    index_error: str | None = None


class StoryCommitCoordinator:
    """Persist the aggregate first; acknowledge outbox events only after projection success."""

    def __init__(self, repository: StoryRepository, indexes: DerivedIndexService) -> None:
        self.repository = repository
        self.indexes = indexes

    def save(self, story: Story) -> CommitResult:
        snapshot = story.model_copy(deep=True)
        snapshot.assert_consistent()
        self.repository.save(snapshot)
        return CommitResult(snapshot, None)

    def save_and_reindex(self, story: Story, event_type: str) -> CommitResult:
        snapshot = story.model_copy(deep=True)
        snapshot.assert_consistent()
        self.repository.save(snapshot, event_type=event_type)
        try:
            summary = self.indexes.rebuild(snapshot)
        except Exception as exc:
            return CommitResult(snapshot, None, str(exc))
        event_ids = self.repository.pending_index_event_ids(snapshot.id)
        self.repository.mark_index_events_processed(event_ids)
        return CommitResult(snapshot, summary)


__all__ = ["CommitResult", "StoryCommitCoordinator"]
