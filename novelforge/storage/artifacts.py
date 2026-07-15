"""Non-canonical artifact storage.

Artifacts are user-facing exports and diagnostics. They are never used to
restore a story and may be deleted independently from canonical state.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID


class ArtifactStore:
    """Allocate and remove paths below one explicit artifact root."""

    def __init__(self, root: str | Path = "./.data/novelforge/artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def story_root(self, story_id: str | UUID) -> Path:
        """Return the artifact root for one story without creating it."""
        return self.root / "stories" / str(story_id)

    def path(self, story_id: str | UUID, category: str, filename: str) -> Path:
        """Create and return a safe artifact path for one story."""
        if not category or Path(category).name != category:
            raise ValueError("Artifact category must be one directory name.")
        if not filename or Path(filename).name != filename:
            raise ValueError("Artifact filename must not contain a path.")

        path = self.story_root(story_id) / category / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def delete_story(self, story_id: str | UUID) -> bool:
        """Delete only non-canonical artifacts belonging to one story."""
        root = self.story_root(story_id)
        if not root.exists():
            return False
        shutil.rmtree(root)
        return True
