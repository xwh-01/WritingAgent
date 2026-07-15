from __future__ import annotations

import os

from fastapi.testclient import TestClient
import pytest

from novelforge.agents.continuity_auditor import ContinuityAuditorAgent
from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.models import Chapter, ChapterOutline, ContinuityAuditReport, Foreshadowing, Story
from novelforge.llm.mock_client import MockLLMClient
from novelforge.orchestrator.engine import NovelForgeEngine


def test_continuity_auditor_flags_overdue_foreshadowing() -> None:
    story = Story(title="Audit", premise="Long story")
    story.content.outlines = [
        ChapterOutline(chapter_index=2, title="Due", summary="Resolve the clue.", conflict="The old clue must matter.")
    ]
    story.memory.foreshadowings.append(
        Foreshadowing(id="fs-1", description="The glove hides a secret.", created_chapter=1, target_chapter=2)
    )
    auditor = ContinuityAuditorAgent(MockLLMClient())

    report = auditor._rule_audit(story, 2, "The chapter discusses training but ignores the glove.", story.content.outlines[0])

    assert not report.passed
    assert any(issue.dimension == "foreshadowing" for issue in report.issues)


def test_engine_records_continuity_report_after_writing(test_config) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("A goalkeeper learns anticipation.", title="Audit Engine")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="First Save", summary="The hero discovers anticipation.", conflict="He must prove himself.")
    ]

    chapter = engine.write_chapter(1)

    assert chapter.content
    assert 1 in story.quality.continuity_reports
    assert story.quality.continuity_reports[1].risk_score >= 0


def test_candidate_continuity_audit_uses_candidate_without_persisting(test_config, monkeypatch) -> None:
    engine = NovelForgeEngine(config=test_config)
    story = engine.start_new_story("Premise", title="Candidate audit")
    story.content.outlines = [
        ChapterOutline(chapter_index=1, title="One", summary="Summary", conflict="Conflict")
    ]
    story.content.chapters[1] = Chapter(index=1, title="One", content="official content")
    seen: dict[str, str] = {}
    expected = ContinuityAuditReport(chapter_index=1, summary="candidate only")

    monkeypatch.setattr(
        engine.longform_manager,
        "get_enhanced_context",
        lambda *_args, **_kwargs: "longform context",
    )

    def audit(_story, _index, content, context):
        seen["content"] = content
        seen["context"] = context
        return expected

    monkeypatch.setattr(engine.continuity_auditor, "audit_chapter", audit)
    monkeypatch.setattr(engine, "save_state", lambda: pytest.fail("candidate audit must not save"))

    report = engine._audit_candidate_continuity(story, 1, "candidate content")

    assert report is expected
    assert seen == {"content": "candidate content", "context": "longform context"}
    assert story.content.chapters[1].content == "official content"
    assert story.quality.continuity_reports == {}


def test_report_api_includes_continuity_report() -> None:
    os.environ["NOVELFORGE_LLM_PROVIDER"] = "mock"
    ENGINES.clear()
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "A goalkeeper learns anticipation.", "title": "Audit API"})
    story_id = created.json()["story"]["id"]
    client.post(f"/stories/{story_id}/outline", json={"num_chapters": 1})
    client.put(
        f"/chapters/1/content",
        params={"story_id": story_id},
        json={"title": "First Save", "content": "The hero trains hard and discovers a clue.", "status": "draft"},
    )

    response = client.get(f"/chapters/1/report", params={"story_id": story_id})

    assert response.status_code == 200
    assert "continuity_report" in response.json()
