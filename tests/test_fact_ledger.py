from __future__ import annotations

from fastapi.testclient import TestClient

from novelforge.api.main import app
from novelforge.api.state import ENGINES
from novelforge.core.models import Character, CharacterFact, CharacterState, Story
from novelforge.longform.fact_ledger import CharacterFactLedger


def test_fact_ledger_builds_temporal_intervals() -> None:
    story = Story(title="Facts", premise="A journey")
    story.content.characters["hero"] = Character(id="hero", name="Hero")
    story.memory.states["hero"] = [
        CharacterState(character_id="hero", chapter=1, location="village", emotional_state="calm"),
        CharacterState(
            character_id="hero",
            chapter=3,
            location="capital",
            emotional_state="afraid",
            knowledge_gained=["the king is missing"],
        ),
    ]
    ledger = CharacterFactLedger()

    ledger.rebuild_from_states(story)

    chapter_two = ledger.facts_at(story, 2)
    chapter_three = ledger.facts_at(story, 3)
    assert any(fact.fact_type == "location" and fact.value == "village" for fact in chapter_two)
    assert any(fact.fact_type == "location" and fact.value == "capital" for fact in chapter_three)
    assert not any(fact.fact_type == "knowledge" for fact in chapter_two)
    assert any(fact.fact_type == "knowledge" for fact in chapter_three)


def test_confirmed_fact_overrides_extracted_fact_only_in_its_interval() -> None:
    story = Story(title="Override", premise="A mystery")
    story.memory.states["hero"] = [
        CharacterState(character_id="hero", chapter=1, location="station")
    ]
    ledger = CharacterFactLedger()
    ledger.rebuild_from_states(story)
    ledger.upsert_confirmed(story, CharacterFact(
        id="manual-location",
        character_id="hero",
        fact_type="location",
        value="hospital",
        valid_from_chapter=2,
        valid_until_chapter=4,
    ))

    assert [fact.value for fact in ledger.facts_at(story, 3) if fact.fact_type == "location"] == ["hospital"]
    assert [fact.value for fact in ledger.facts_at(story, 5) if fact.fact_type == "location"] == ["station"]


def test_fact_api_persists_user_confirmed_fact() -> None:
    ENGINES.clear()
    client = TestClient(app)
    created = client.post("/stories/", json={"premise": "facts", "title": "Fact API"})
    story_id = created.json()["story"]["id"]

    saved = client.post(f"/stories/{story_id}/facts", json={
        "id": "manual-life",
        "character_id": "hero",
        "fact_type": "life_status",
        "value": "alive",
        "valid_from_chapter": 1,
    })
    listed = client.get(f"/stories/{story_id}/facts", params={"chapter_index": 2})

    assert saved.status_code == 200
    assert saved.json()["user_confirmed"] is True
    assert listed.json()["facts"][0]["id"] == "manual-life"

    deleted = client.delete(f"/stories/{story_id}/facts/manual-life")
    after_delete = client.get(f"/stories/{story_id}/facts", params={"chapter_index": 2})

    assert deleted.status_code == 200
    assert after_delete.json()["facts"] == []
