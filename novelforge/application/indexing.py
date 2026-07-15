"""Management of disposable search and graph indexes."""

from __future__ import annotations

from typing import Any

from novelforge.domain import Chapter, Story
from novelforge.indexes.interfaces import IFTSStore, IGraphStore, IVectorStore


class DerivedIndexService:
    """Own all writes to rebuildable vector, text, and graph indexes.

    This service never reads or writes the canonical repository. It receives a
    Story snapshot and can therefore be cleared or rebuilt safely.
    """

    def __init__(
        self,
        vector_store: IVectorStore,
        text_store: IFTSStore,
        graph_store: IGraphStore,
    ) -> None:
        self.vector_store = vector_store
        self.text_store = text_store
        self.graph_store = graph_store

    def delete_story(self, story_id: str) -> dict[str, int]:
        """Delete every derived entry for one story."""
        return {
            "vector_items": self.vector_store.delete_story(story_id),
            "fts_items": self.text_store.delete_story(story_id),
            "graph_nodes": self.graph_store.delete_story(story_id),
        }

    def rebuild(self, story: Story) -> dict[str, int | str]:
        """Recreate derived indexes exclusively from canonical story state."""
        story = story.model_copy(deep=True)
        story_id = str(story.id)
        self.delete_story(story_id)

        indexed_chapters = 0
        for chapter in story.manuscript.chapters.values():
            if chapter.content:
                self.index_chapter(story, chapter)
                indexed_chapters += 1

        notes = story.knowledge.retrieval_notes
        self.index_retrieval_notes(story, notes)

        characters_by_id = {
            observation.character_id: observation
            for observation in story.knowledge.character_observations
        }
        characters_by_id.update(story.design.characters)
        characters = list(characters_by_id.values())
        self._index_characters(story_id, characters)
        self._index_character_relationships(story, characters)

        world_by_id = {fact.fact_id: fact for fact in story.knowledge.world_facts}
        world_by_id.update({setting.id: setting for setting in story.design.world_settings})
        world_settings = list(world_by_id.values())
        self._index_world_settings(story_id, world_settings)

        return {
            "story_id": story_id,
            "chapters": indexed_chapters,
            "retrieval_notes": len(notes),
            "characters": len(characters),
            "world_settings": len(world_settings),
        }

    def index_retrieval_notes(self, story: Story, notes: list[Any]) -> None:
        """Write compact knowledge notes to the vector projection."""
        if not notes:
            return
        story_id = str(story.id)
        self.vector_store.add(
            "knowledge_notes",
            [note.content for note in notes],
            [
                {
                    "story_id": story_id,
                    "type": note.type,
                    "chapter": note.chapter,
                    "importance": note.importance,
                    "entities": ",".join(note.entities),
                    "tags": ",".join(note.tags),
                }
                for note in notes
            ],
            [self._retrieval_note_id(story_id, note.id) for note in notes],
        )

    def index_chapter(self, story: Story, chapter: Chapter) -> None:
        """Replace the current full-text and summary index for a chapter."""
        prefix = f"{story.id}:chapter:{chapter.index}:"
        self.text_store.delete_prefix(prefix)
        self.vector_store.delete_prefix("plot_summaries", prefix)
        document_id = f"{prefix}current"
        self.text_store.index_document(document_id, chapter.content)
        self.vector_store.add(
            "plot_summaries",
            [chapter.summary or chapter.content[:500]],
            [
                {
                    "story_id": str(story.id),
                    "type": "chapter_summary",
                    "chapter": chapter.index,
                    "version": chapter.version,
                }
            ],
            [document_id],
        )

    def _index_characters(self, story_id: str, characters: list[Any]) -> None:
        if not characters:
            return
        self.vector_store.add(
            "characters",
            [self._character_document(character) for character in characters],
            [
                {
                    "story_id": story_id,
                    "type": "character",
                    "character_id": self._character_id(character),
                }
                for character in characters
            ],
            [f"{story_id}:character:{self._character_id(character)}" for character in characters],
        )
        for character in characters:
            attributes = character.model_dump()
            attributes["story_id"] = story_id
            self.graph_store.add_node(
                f"{story_id}:character:{self._character_id(character)}",
                attributes,
            )

    def _index_world_settings(self, story_id: str, settings: list[Any]) -> None:
        if not settings:
            return
        self.vector_store.add(
            "world",
            [setting.content for setting in settings],
            [
                {
                    "story_id": story_id,
                    "type": "world",
                    "category": setting.category,
                    **setting.metadata,
                }
                for setting in settings
            ],
            [f"{story_id}:world:{self._world_id(setting)}" for setting in settings],
        )

    def _index_character_relationships(self, story: Story, characters: list[Any]) -> None:
        story_id = str(story.id)
        known_ids = {self._character_id(character) for character in characters}
        for character in characters:
            source_id = self._character_id(character)
            for target_id, relation in getattr(character, "relationships", {}).items():
                if target_id not in known_ids:
                    continue
                self.graph_store.add_edge(
                    f"{story_id}:character:{source_id}",
                    f"{story_id}:character:{target_id}",
                    relation,
                )
        for fact in story.knowledge.relationships:
            if fact.source not in known_ids or fact.target not in known_ids:
                continue
            self.graph_store.add_edge(
                f"{story_id}:character:{fact.source}",
                f"{story_id}:character:{fact.target}",
                fact.relation,
            )

    @staticmethod
    def _character_document(character: Any) -> str:
        return " ".join(
            str(value)
            for value in (
                character.name,
                getattr(character, "age", None),
                character.appearance,
                character.personality,
                character.motivation,
                getattr(character, "weakness", ""),
                getattr(character, "arc", ""),
            )
            if value
        )

    @staticmethod
    def _character_id(character: Any) -> str:
        return str(getattr(character, "id", None) or getattr(character, "character_id"))

    @staticmethod
    def _world_id(setting: Any) -> str:
        return str(getattr(setting, "id", None) or getattr(setting, "fact_id"))

    @staticmethod
    def _retrieval_note_id(story_id: str, note_id: str) -> str:
        if note_id.startswith(f"{story_id}:"):
            return note_id
        return f"{story_id}:retrieval_note:{note_id}"
