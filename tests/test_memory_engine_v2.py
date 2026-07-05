from __future__ import annotations

from novelforge.core.models import Character, Story
from novelforge.llm.mock_client import MockLLMClient
from novelforge.longform.manager import LongformManager
from novelforge.orchestrator.engine import NovelForgeEngine


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


def test_engine_indexes_memory_cards_after_writing(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A long sports saga.", title="Memory Index")
    engine.generate_outline(2)

    engine.write_chapter(1)
    context = engine.context_assembler.assemble_writing_context(2, story)
    retrieved = engine.vector_store.query("memory_cards", "sports saga secret training", k=5)

    assert story.memory_cards
    assert story.arc_summaries
    assert retrieved
    assert "Memory Engine v2 Context Pack" in context
