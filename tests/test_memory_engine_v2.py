from __future__ import annotations

from novelforge.agents.memory_extractor import MemoryExtractorAgent
from novelforge.core.models import CausalEvent, Character, CharacterState, Foreshadowing, MemoryCard, Story
from novelforge.llm.mock_client import MockLLMClient
from novelforge.longform.manager import LongformManager
from novelforge.longform.ranker import MemoryRanker
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.memory.vector_store import InMemoryVectorStore
from novelforge.memory.text_store import SQLiteFTSStore


def test_memory_engine_v2_builds_long_novel_memory() -> None:
    story = Story(title="Memory", premise="A goalkeeper grows across a thousand-chapter saga.")
    story.characters["hero"] = Character(id="hero", name="Wang Shaokang")
    manager = LongformManager(MockLLMClient())

    result = manager.process_new_chapter(
        story,
        1,
        "Wang Shaokang discovers a secret training method on the football field. "
        "He decides to protect the clue until the truth is revealed.",
    )
    context = manager.get_enhanced_context(2, story)

    assert result["memory"]["memory_cards"]
    assert story.memory_cards
    assert story.arc_summaries
    assert story.story_bible.core_premise == story.premise
    assert "Memory Engine v2 Context Pack" in context
    assert "Retrieved Memory Cards" in context


def test_memory_extractor_rules_find_character_and_world_facts() -> None:
    story = Story(title="Goalkeeper", premise="王绍康 becomes a goalkeeper.")
    extractor = MemoryExtractorAgent(None)

    content = "王绍康在球场训练门将扑救，他把王者荣耀后羿的预判方式用在足球上。但训练中他受了伤，而且还有一个秘密没有告诉队友。"
    result = extractor.extract_chapter_memory(
        story,
        1,
        content,
    )
    repeated = extractor.extract_chapter_memory(story, 1, content)

    # Generic Chinese name detection should find "王绍康" (surname 王)
    assert any(character.name == "王绍康" for character in result.characters)
    # Content mentions skill/ability patterns — should detect at least one world setting
    assert len(result.world_settings) >= 1
    # Deterministic IDs — same input → same output
    assert [setting.id for setting in result.world_settings] == [setting.id for setting in repeated.world_settings]
    # Generic constraint detection should find at least one constraint
    assert result.continuity_constraints


def test_engine_indexes_memory_cards_after_writing(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A long sports saga.", title="Memory Index")
    engine.generate_outline(2)

    engine.write_chapter(1)
    context = engine.context_assembler.assemble_writing_context(2, story)
    retrieved = engine.vector_store.query("memory_cards", "sports saga secret training", k=5)

    assert story.memory_cards
    assert story.arc_summaries
    assert story.characters
    assert story.world_settings
    assert retrieved
    assert engine.vector_store.query("characters", "主角 training", k=5)
    # Verify graph store has character nodes (mock returns character id="protagonist")
    char_id = next(iter(story.characters.keys()))
    assert engine.graph_store.get_ego_network(f"{story.id}:character:{char_id}", depth=1)["nodes"]
    assert "Memory Engine v2 Context Pack" in context
    assert "score=" in context


def test_memory_ranker_prioritizes_entity_and_foreshadowing() -> None:
    ranker = MemoryRanker()
    cards = [
        MemoryCard(id="old", type="chapter_summary", content="unrelated market scene", chapter=1, importance=9),
        MemoryCard(
            id="hero-fs",
            type="foreshadowing",
            content="Wang Shaokang has an unresolved anticipation secret",
            chapter=20,
            importance=8,
            entities=["hero"],
            tags=["secret"],
        ),
    ]

    ranked = ranker.rank_cards(cards, "Wang Shaokang anticipation", 30, entities={"hero"})

    assert ranked[0].item.id == "hero-fs"
    assert "entity" in ranked[0].reasons
    assert "query" in ranked[0].reasons


def test_memory_ranker_excludes_future_chapters() -> None:
    ranker = MemoryRanker()
    cards = [
        MemoryCard(id="past", type="chapter_summary", content="past clue", chapter=2),
        MemoryCard(id="current", type="chapter_summary", content="current secret", chapter=3),
        MemoryCard(id="future", type="chapter_summary", content="future reveal", chapter=8),
    ]

    ranked = ranker.rank_cards(cards, "secret reveal", current_chapter=3)

    assert {item.item.id for item in ranked} == {"past", "current"}


def test_vector_query_enforces_chapter_visibility() -> None:
    store = InMemoryVectorStore()
    store.add(
        "plot_summaries",
        ["past clue", "future secret"],
        [{"story_id": "s1", "chapter": 1}, {"story_id": "s1", "chapter": 5}],
        ["s1:chapter:1:current", "s1:chapter:5:current"],
    )

    hits = store.query("plot_summaries", "secret clue", k=10, story_id="s1", max_chapter=3)

    assert [item["id"] for item in hits] == ["s1:chapter:1:current"]


def test_context_pack_does_not_expose_future_structured_state() -> None:
    story = Story(title="Temporal", premise="A mystery")
    story.characters["hero"] = Character(id="hero", name="Hero")
    story.character_states["hero"] = [
        CharacterState(character_id="hero", chapter=1, location="station"),
        CharacterState(character_id="hero", chapter=6, location="moon"),
    ]
    story.foreshadowings = [
        Foreshadowing(id="past", description="old key", created_chapter=1),
        Foreshadowing(id="future", description="future crown", created_chapter=7),
    ]
    story.causal_events = [
        CausalEvent(id="past-event", chapter=1, description="door opened"),
        CausalEvent(id="future-event", chapter=9, description="world ended"),
    ]

    context = LongformManager(None).get_enhanced_context(3, story)

    assert "station" in context
    assert "old key" in context
    assert "door opened" in context
    assert "moon" not in context
    assert "future crown" not in context
    assert "world ended" not in context


def test_fulltext_visibility_and_chapter_replacement(test_config) -> None:
    engine = NovelForgeEngine(test_config)
    story = engine.start_new_story("versioned memory", title="Versions")
    engine.generate_outline(2)
    chapter = engine.generate_beats(1)
    chapter.content = "obsolete draft marker"
    engine._index_chapter(story, chapter)
    chapter.version += 1
    chapter.content = "current draft marker"
    engine._index_chapter(story, chapter)

    prefix = f"{story.id}:chapter:1:"
    hits = engine.vector_store.query("plot_summaries", "draft marker", k=10, story_id=str(story.id))

    assert [item["id"] for item in hits if item["id"].startswith(prefix)] == [f"{prefix}current"]
    assert engine.text_store.search("obsolete", story_id=str(story.id)) == []
    assert engine.text_store.search("current", story_id=str(story.id)) == ["current draft marker"]


def test_fulltext_search_excludes_future_chapters(tmp_path) -> None:
    store = SQLiteFTSStore(str(tmp_path / "temporal.sqlite3"))
    store.index_document("s1:chapter:2:current", "shared clue from past")
    store.index_document("s1:chapter:8:current", "shared clue from future")

    results = store.search("shared clue", story_id="s1", max_chapter=3)

    assert results == ["shared clue from past"]
