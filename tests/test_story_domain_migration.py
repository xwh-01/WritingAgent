"""Tests for the 4-domain Story structure migration and enforcement."""

from __future__ import annotations

import json

import pytest

from novelforge.core.models import (
    AgentTraceRun,
    AutoRevisionReport,
    BatchWriteReport,
    Chapter,
    ChapterContract,
    ChapterOutline,
    ChapterSummary,
    Character,
    CharacterFact,
    CharacterState,
    ContinuityAuditReport,
    Foreshadowing,
    MemoryCard,
    RevisionProposal,
    Story,
    StoryBible,
    WorldSetting,
)


# ---------------------------------------------------------------------------
# 1. Old flat Story JSON can be loaded.
# ---------------------------------------------------------------------------
def test_old_flat_story_json_loads_and_migrates() -> None:
    old_data = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Test Novel",
        "premise": "A test premise.",
        "genre": "novel",
        "style_guide": "",
        "current_chapter": 1,
        "status": "planning",
        # Flat content fields
        "characters": {"hero": {"id": "hero", "name": "Hero"}},
        "world_settings": [{"id": "ws-1", "category": "location", "content": "Castle"}],
        "outlines": [{"chapter_index": 1, "title": "Ch1", "summary": "...", "conflict": "..."}],
        "chapter_contracts": {},
        "chapters": {
            "1": {"index": 1, "title": "Ch1", "content": "Once upon a time.", "version": 1, "status": "draft"}
        },
        # Flat memory fields
        "character_facts": [],
        "character_states": {},
        "foreshadowings": [],
        "causal_events": [],
        "chapter_summaries": {},
        "volume_summaries": [],
        "arc_summaries": [],
        "story_bible": {},
        "memory_cards": [],
        # Flat quality fields
        "auto_revision_reports": {},
        "continuity_reports": {},
        "character_continuity_reports": [],
        "revision_proposals": [],
        # Flat agent fields
        "agent_trace_runs": [],
        "batch_reports": [],
        "agent_runs": [],
    }

    story = Story.model_validate(old_data)
    assert story.title == "Test Novel"
    assert list(story.content.characters.keys()) == ["hero"]
    assert len(story.content.outlines) == 1
    assert 1 in story.content.chapters
    assert story.content.chapters[1].content == "Once upon a time."
    assert isinstance(story.memory.facts, list)
    assert isinstance(story.memory.states, dict)
    assert isinstance(story.memory.cards, list)
    assert isinstance(story.memory.story_bible, StoryBible)
    assert isinstance(story.quality.auto_revision_reports, dict)
    assert isinstance(story.quality.revision_proposals, list)
    assert isinstance(story.agent_runs.director, list)
    assert isinstance(story.agent_runs.batch_reports, list)


# ---------------------------------------------------------------------------
# 2. After serialization, output only contains the 4-domain structure.
# ---------------------------------------------------------------------------
def test_serialized_story_only_has_four_domains() -> None:
    story = Story(title="Clean", premise="No old fields.", genre="novel")

    dumped = story.model_dump(mode="json")
    top_level_keys = set(dumped.keys())

    expected_top = {
        "id", "title", "premise", "genre", "style_guide",
        "content", "memory", "quality", "agent_runs",
        "current_chapter", "status", "created_at", "updated_at",
    }
    assert top_level_keys == expected_top, f"Unexpected keys: {top_level_keys - expected_top}"

    # The four domains must be present and have the correct sub-keys
    assert set(dumped["content"].keys()) == {"characters", "world_settings", "outlines", "chapter_contracts", "chapters"}
    assert set(dumped["memory"].keys()) == {
        "facts", "states", "foreshadowings", "causal_events",
        "chapter_summaries", "volume_summaries", "arc_summaries",
        "story_bible", "cards",
    }
    assert set(dumped["quality"].keys()) == {
        "auto_revision_reports", "continuity_reports",
        "character_continuity_reports", "revision_proposals",
    }
    assert set(dumped["agent_runs"].keys()) == {"autonomous", "director", "batch_reports"}


# ---------------------------------------------------------------------------
# 3. Story no longer has chapters, character_facts, etc. as flat attributes.
# ---------------------------------------------------------------------------
def test_story_has_no_flat_properties() -> None:
    story = Story(title="No Flat", premise="Checking.")

    flat_names = [
        "outlines", "chapter_contracts", "chapters", "characters", "world_settings",
        "character_facts", "character_states", "foreshadowings", "causal_events",
        "chapter_summaries", "volume_summaries", "arc_summaries", "story_bible",
        "memory_cards", "auto_revision_reports", "continuity_reports",
        "character_continuity_reports", "revision_proposals",
        "agent_trace_runs", "batch_reports",
    ]
    for name in flat_names:
        assert not hasattr(story, name), f"Story should not have flat property '{name}'"


# ---------------------------------------------------------------------------
# 4. Create story, generate outlines, write chapter can run end-to-end.
# ---------------------------------------------------------------------------
def test_basic_workflow_runs_with_new_structure() -> None:
    story = Story(title="Workflow Test", premise="Testing workflow.", genre="fantasy")

    # Add outlines
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="Start", summary="Beginning.", conflict="Conflict A"),
    ]
    assert len(story.content.outlines) == 1

    # Add a chapter
    chapter = Chapter(index=1, title="Start", content="It was a dark night.", status="draft")
    story.content.chapters[1] = chapter
    assert story.content.chapters[1].content == "It was a dark night."
    assert story.current_chapter == 0  # current_chapter not auto-set without service

    # Add characters
    story.content.characters["hero"] = Character(id="hero", name="Aragorn")
    assert "hero" in story.content.characters

    # Add facts
    story.memory.facts.append(
        CharacterFact(
            id="fact-1", character_id="hero", fact_type="location",
            value="Rivendell", valid_from_chapter=1, user_confirmed=True,
        )
    )
    assert len(story.memory.facts) == 1

    # Add foreshadowing
    story.memory.foreshadowings.append(
        Foreshadowing(id="fs-1", description="A shadow looms.", created_chapter=1, status="pending")
    )
    assert len(story.memory.foreshadowings) == 1


# ---------------------------------------------------------------------------
# 5. Director run and BatchReport save to agent_runs.
# ---------------------------------------------------------------------------
def test_agent_runs_accept_director_and_batch() -> None:
    story = Story(title="Agent Test", premise="Testing agent runs.")

    # Director run
    run = AgentTraceRun(
        id="run-1", story_id=str(story.id), user_message="Write ch1",
        status="completed", steps=[], final_summary="Done.",
    )
    story.agent_runs.director.append(run)
    assert len(story.agent_runs.director) == 1

    # Batch report
    report = BatchWriteReport(start_chapter=1, end_chapter=3, completed=3)
    story.agent_runs.batch_reports.append(report)
    assert len(story.agent_runs.batch_reports) == 1


# ---------------------------------------------------------------------------
# 6. API response no longer returns both content.chapters AND chapters.
# ---------------------------------------------------------------------------
def test_model_dump_is_clean() -> None:
    story = Story(title="API Test", premise="Clean output.")
    story.content.chapters[1] = Chapter(index=1, title="Ch1", content="Text.", status="draft")

    json_str = story.model_dump_json()
    data = json.loads(json_str)

    # Should NOT have flat "chapters" at top level
    assert "chapters" not in data
    # Should have it inside content
    assert "chapters" in data["content"]
    assert "1" in data["content"]["chapters"]

    # Same for all other domains
    assert "character_facts" not in data
    assert "facts" in data["memory"]
    assert "memory_cards" not in data
    assert "cards" in data["memory"]
    assert "auto_revision_reports" not in data
    assert "auto_revision_reports" in data["quality"]
    assert "agent_trace_runs" not in data
    assert "director" in data["agent_runs"]
    assert "batch_reports" not in data
    assert "batch_reports" in data["agent_runs"]


# ---------------------------------------------------------------------------
# 7. A sentinel test that the repo has no remaining flat property access.
#    This scans Python source under novelforge/ (excluding models.py and the
#    migration validator) for the old patterns.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("old_attr", [
    "story.chapters[",
    "story.characters[",
    "story.world_settings",
    "story.outlines[",
    "story.chapter_contracts",
    "story.character_facts",
    "story.character_states",
    "story.foreshadowings",
    "story.causal_events",
    "story.chapter_summaries",
    "story.volume_summaries",
    "story.arc_summaries",
    "story.story_bible.",
    "story.memory_cards",
    "story.auto_revision_reports",
    "story.continuity_reports[",
    "story.character_continuity_reports",
    "story.revision_proposals",
    "story.agent_trace_runs",
    "story.batch_reports",
])
def test_no_flat_property_in_business_code(old_attr: str) -> None:
    """Ensure no business code uses deprecated flat Story property access."""
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    novelforge_dir = repo_root / "novelforge"

    # Files allowed to contain old-style strings (migration logic, this test)
    allowed = {"core/models.py", "application/story_domains.py"}

    violations: list[str] = []
    for py_file in novelforge_dir.rglob("*.py"):
        rel = str(py_file.relative_to(repo_root)).replace("\\", "/")
        if rel in allowed:
            continue
        content = py_file.read_text(encoding="utf-8")
        if old_attr in content:
            violations.append(f"{rel}: contains '{old_attr}'")

    assert not violations, f"Files with deprecated flat property access: {violations}"
