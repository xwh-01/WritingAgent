from __future__ import annotations

import os

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.context.assembler import ContextAssembler
from novelforge.core.models import Character, Chapter, ChapterOutline, Story
from novelforge.memory.graph_store import NetworkXGraphStore
from novelforge.memory.text_store import SQLiteFTSStore
from novelforge.memory.vector_store import InMemoryVectorStore
from novelforge.storage.repository import StoryRepository


def test_repository_delete_removes_story_file(tmp_path) -> None:
    repository = StoryRepository(tmp_path)
    story = Story(title="Delete Me", premise="cleanup")
    path = repository.save(story)

    assert path.exists()
    assert repository.delete(story.id)
    assert not path.exists()
    assert not repository.delete(story.id)


def test_memory_backends_delete_story(tmp_path) -> None:
    story_id = "story-a"
    vector = InMemoryVectorStore()
    vector.add("memory_cards", ["a"], [{"story_id": story_id}], [f"{story_id}:card:1"])
    vector.add("memory_cards", ["b"], [{"story_id": "story-b"}], ["story-b:card:1"])

    fts = SQLiteFTSStore(str(tmp_path / "fts.sqlite3"))
    fts.index_document(f"{story_id}:chapter:1:v1", "alpha cleanup")
    fts.index_document("story-b:chapter:1:v1", "alpha keep")

    graph = NetworkXGraphStore(str(tmp_path / "graph"))
    graph.add_node(f"{story_id}:character:hero", {"story_id": story_id})
    graph.add_node("story-b:character:hero", {"story_id": "story-b"})

    assert vector.delete_story(story_id) == 1
    assert fts.delete_story(story_id) == 1
    assert graph.delete_story(story_id) == 1
    remaining_ids = {item["id"] for item in vector.query("memory_cards", "a", k=5)}
    assert f"{story_id}:card:1" not in remaining_ids
    assert "story-b:card:1" in remaining_ids
    assert fts.search("cleanup") == []
    assert graph.get_ego_network(f"{story_id}:character:hero")["nodes"] == {}


def test_context_retrieval_is_scoped_to_story(tmp_path) -> None:
    story = Story(title="Scoped", premise="own premise")
    story.characters["hero"] = Character(id="hero", name="Hero")
    story.outlines.append(
        ChapterOutline(
            chapter_index=1,
            title="Shared clue",
            summary="shared memory clue",
            conflict="resolve shared conflict",
            pov_character="hero",
        )
    )
    own_id = str(story.id)
    other_id = "other-story"

    vector = InMemoryVectorStore()
    vector.add("memory_cards", ["own vector shared memory clue"], [{"story_id": own_id}], [f"{own_id}:card:1"])
    vector.add("memory_cards", ["other vector shared memory clue"], [{"story_id": other_id}], [f"{other_id}:card:1"])

    fts = SQLiteFTSStore(str(tmp_path / "fts.sqlite3"))
    fts.index_document(
        f"{own_id}:chapter:1:v1",
        "Shared clue shared memory clue resolve shared conflict hero own fulltext marker",
    )
    fts.index_document(
        f"{other_id}:chapter:1:v1",
        "Shared clue shared memory clue resolve shared conflict hero other fulltext marker",
    )

    graph = NetworkXGraphStore(str(tmp_path / "graph"))
    graph.add_node(f"{own_id}:character:hero", {"story_id": own_id, "name": "Own Hero"})
    graph.add_node(f"{other_id}:character:hero", {"story_id": other_id, "name": "Other Hero"})

    context = ContextAssembler(vector, graph, fts).assemble_writing_context(1, story)

    assert "own vector shared memory clue" in context
    assert "own fulltext marker" in context
    assert "Own Hero" in context
    assert "other vector shared memory clue" not in context
    assert "other fulltext marker" not in context
    assert "Other Hero" not in context


def test_delete_story_api_removes_file_and_engine() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "cleanup", "title": "Delete API"})
    story_id = created.json()["story"]["id"]
    engine = ENGINES[story_id]
    engine.story.characters["hero"] = Character(id="hero", name="Hero")
    engine.story.chapters[1] = Chapter(index=1, title="One", content="cleanup memory")
    engine._process_chapter_memory(engine.story, engine.story.chapters[1])
    engine.save_state()

    response = client.delete(f"/stories/{story_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert story_id not in ENGINES
    assert not StoryRepository().exists(story_id)
