from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novelforge.core.config import AppConfig, LLMConfig, LoggingConfig, MemoryConfig, StorageConfig, StoryConfig


@pytest.fixture()
def test_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(
            persist_directory=str(tmp_path / "chroma"),
            graph_directory=str(tmp_path / "graph"),
            sqlite_path=str(tmp_path / "fts.sqlite3"),
        ),
        storage=StorageConfig(
            database_path=str(tmp_path / "novelforge.db"),
            artifact_directory=str(tmp_path / "artifacts"),
            legacy_state_directory=str(tmp_path / "legacy_story_state"),
        ),
        story=StoryConfig(default_chapters=3, max_context_tokens=1000),
        logging=LoggingConfig(level="DEBUG"),
    )
