"""Application-level coordination for all story storage classes."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from novelforge.application.indexing import DerivedIndexService
from novelforge.domain import Story
from novelforge.storage.agent_runs import AgentRunRepository
from novelforge.storage.artifacts import ArtifactStore
from novelforge.storage.repository import StoryRepository


class StoryStorageService:
    """Coordinate canonical state, artifacts, and disposable indexes.

    This is the only service allowed to perform a cross-store operation such
    as deleting all data for a story or reporting the complete storage layout.
    """

    def __init__(
        self,
        repository: StoryRepository,
        agent_runs: AgentRunRepository,
        artifacts: ArtifactStore,
        indexes: DerivedIndexService,
        *,
        vector_path: str | Path,
        graph_path: str | Path,
        full_text_path: str | Path,
    ) -> None:
        self.repository = repository
        self.agent_runs = agent_runs
        self.artifacts = artifacts
        self.indexes = indexes
        self.index_locations = {
            "vector": str(vector_path),
            "graph": str(graph_path),
            "full_text": str(full_text_path),
        }

    def status(self, story_id: str | UUID) -> dict[str, object]:
        """Describe ownership and synchronization state for one story."""
        return {
            "story_id": str(story_id),
            "canonical_store": str(self.repository.database_path),
            "agent_run_store": str(self.agent_runs.database_path),
            "agent_runs": len(self.agent_runs.list_runs(story_id)),
            "revision_proposals": len(self.agent_runs.list_revision_proposals(story_id)),
            "artifact_directory": str(self.artifacts.story_root(story_id)),
            "derived_indexes": dict(self.index_locations),
            "pending_index_events": self.repository.pending_index_event_count(story_id),
        }

    def delete_story(self, story_id: str | UUID) -> dict[str, object]:
        """Delete one story from every storage class."""
        normalized = str(story_id)
        derived = self.indexes.delete_story(normalized)
        artifacts_deleted = self.artifacts.delete_story(normalized)
        operational_deleted = self.agent_runs.delete_story(normalized)
        canonical_deleted = self.repository.delete(normalized)
        return {
            "story_id": normalized,
            "canonical_deleted": canonical_deleted,
            "artifacts_deleted": artifacts_deleted,
            "operational_deleted": operational_deleted,
            **derived,
        }

    def rebuild_indexes(self, story_id: str | UUID) -> dict[str, int | str]:
        """Reload canonical state and rebuild every disposable index from it."""
        story: Story = self.repository.load(story_id)
        result = self.indexes.rebuild(story)
        event_ids = self.repository.pending_index_event_ids(story_id)
        self.repository.mark_index_events_processed(event_ids)
        return {**result, "events_processed": len(event_ids)}
