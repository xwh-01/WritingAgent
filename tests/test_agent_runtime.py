from __future__ import annotations

import pytest

from novelforge.core.config import AppConfig
from novelforge.core.exceptions import ConcurrentUpdateError
from novelforge.domain import AgentRunStatus, CandidateStatus, CharacterFact, Story
from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.storage.repository import StoryRepository


def config(tmp_path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "llm": {"provider": "mock"},
            "indexes": {"vector_store": "in_memory"},
            "storage": {
                "database_path": str(tmp_path / "novelforge.db"),
                "artifact_directory": str(tmp_path / "artifacts"),
                "vector_index_directory": str(tmp_path / "vector"),
                "graph_index_directory": str(tmp_path / "graph"),
                "full_text_index_path": str(tmp_path / "fts.sqlite3"),
            },
            "story": {
                "default_chapters": 2,
                "auto_polish_drafts": False,
                "prose_target_words": 600,
            },
            "generation": {"min_quality_score": 6.0, "max_repairs": 1},
        }
    )


def test_orchestrator_plans_records_candidate_and_commits_canon(tmp_path) -> None:
    engine = NovelForgeEngine(config(tmp_path))
    try:
        engine.start_new_story("A courier chooses truth over loyalty.", "Courier")
        run = engine.run_agent_goal("write chapter 1")

        assert run.status is AgentRunStatus.COMPLETED
        details = engine.get_agent_run_details(str(run.id))
        assert [step["tool_name"] for step in details["steps"]] == [
            "create_outline",
            "auto_write_chapter",
        ]
        assert details["candidates"][0]["status"] == CandidateStatus.COMMITTED
        assert details["evaluations"][details["candidates"][0]["id"]]

        story = engine.repository.load(run.story_id)
        assert story.manuscript.chapters[1].content
        assert story.knowledge.sources[1].manuscript_version == 1
        assert "runs" not in story.model_dump()
        story.assert_consistent()
    finally:
        engine.close()


def test_revision_waits_for_approval_outside_story_aggregate(tmp_path) -> None:
    engine = NovelForgeEngine(config(tmp_path))
    try:
        engine.start_new_story("A courier chooses truth over loyalty.", "Courier")
        engine.run_agent_goal("write chapter 1")
        original = engine.current_story.require_chapter(1)

        run = engine.run_agent_goal("revise chapter 1 for stronger conflict")
        assert run.status is AgentRunStatus.WAITING_APPROVAL
        details = engine.get_agent_run_details(str(run.id))
        result = details["steps"][-1]["output_payload"]["tool_result"]
        proposal_id = result["data"]["proposal_id"]
        proposal = engine.get_revision_proposal(proposal_id)
        assert proposal is not None
        assert proposal.scene_patches
        assert engine.current_story.require_chapter(1).version == original.version
        assert "revision_proposals" not in engine.current_story.quality.model_dump()

        revised = engine.accept_revision_proposal(proposal_id)
        resumed = engine.resume_agent_run(str(run.id))
        assert revised.version == original.version + 1
        assert revised.scene_content_is_current()
        assert resumed.status is AgentRunStatus.COMPLETED
        assert engine.agent_run_repository.load_candidate(result["candidate_id"]).status is (
            CandidateStatus.COMMITTED
        )
    finally:
        engine.close()


def test_rejected_agent_candidates_never_enter_canon(tmp_path) -> None:
    strict = config(tmp_path)
    strict.generation.min_quality_score = 10.0
    strict.generation.max_repairs = 0
    engine = NovelForgeEngine(strict)
    try:
        engine.start_new_story("A courier chooses truth over loyalty.", "Courier")
        run = engine.run_agent_goal("write chapter 1")
        assert run.status is AgentRunStatus.FAILED
        assert engine.current_story.manuscript.chapters == {}
        candidates = engine.agent_run_repository.list_candidates(run.id)
        assert candidates
        assert all(item.status is CandidateStatus.REJECTED for item in candidates)
    finally:
        engine.close()


def test_story_repository_rejects_stale_snapshot(tmp_path) -> None:
    repository = StoryRepository(tmp_path / "novelforge.db")
    try:
        created = repository.save(Story(title="Versioned", premise="A premise"))
        first = repository.load(created.id)
        stale = repository.load(created.id)
        first.title = "Fresh"
        saved = repository.save(first)
        assert saved.revision == created.revision + 1

        stale.title = "Stale overwrite"
        with pytest.raises(ConcurrentUpdateError):
            repository.save(stale)
        assert repository.load(created.id).title == "Fresh"
    finally:
        repository.close()


def test_confirmed_fact_is_available_to_exact_search(tmp_path) -> None:
    engine = NovelForgeEngine(config(tmp_path))
    try:
        story = engine.start_new_story("A courier chooses truth.", "Courier")
        engine.upsert_character_fact(
            CharacterFact(
                character_id="courier",
                fact_type="inventory",
                value="SilverKey",
                valid_from_chapter=1,
                user_confirmed=True,
            )
        )
        matches = engine.text_store.search("SilverKey", story_id=str(story.id))
        assert matches and "SilverKey" in matches[0]
    finally:
        engine.close()
