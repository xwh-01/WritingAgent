"""Temporal, user-correctable character fact ledger."""

from __future__ import annotations

import hashlib

from novelforge.domain import CharacterFact, Story


class CharacterFactLedger:
    """Maintain facts with explicit validity intervals and provenance."""

    _SINGLETON_TYPES = {"location", "emotional_state", "life_status", "physical_state"}

    def rebuild_from_states(self, story: Story) -> list[CharacterFact]:
        """Rebuild extracted facts while preserving all user-confirmed overrides."""
        confirmed = [fact for fact in story.knowledge.character_facts if fact.user_confirmed]
        generated: list[CharacterFact] = []
        for character_id, states in story.knowledge.character_states.items():
            for state in sorted(states, key=lambda item: item.chapter):
                if state.location:
                    self._append_temporal(
                        generated, character_id, "location", state.location, state.chapter
                    )
                if state.emotional_state:
                    self._append_temporal(
                        generated,
                        character_id,
                        "emotional_state",
                        state.emotional_state,
                        state.chapter,
                    )
                for knowledge in state.knowledge_gained:
                    self._append_persistent(
                        generated, character_id, "knowledge", knowledge, state.chapter
                    )
                for target, relation in state.relationship_changes.items():
                    self._append_temporal(
                        generated, character_id, f"relationship:{target}", relation, state.chapter
                    )
        story.knowledge.character_facts = sorted(
            generated + confirmed,
            key=lambda fact: (
                fact.valid_from_chapter,
                fact.character_id,
                fact.fact_type,
                fact.user_confirmed,
            ),
        )
        return story.knowledge.character_facts

    def upsert_confirmed(self, story: Story, fact: CharacterFact) -> CharacterFact:
        """Store a user-confirmed fact and make it authoritative for its interval."""
        fact.user_confirmed = True
        fact.confidence = 1.0
        if fact.valid_from_chapter < 1:
            raise ValueError("valid_from_chapter must be >= 1")
        if (
            fact.valid_until_chapter is not None
            and fact.valid_until_chapter < fact.valid_from_chapter
        ):
            raise ValueError("valid_until_chapter must be >= valid_from_chapter")
        story.knowledge.character_facts = [
            item for item in story.knowledge.character_facts if item.id != fact.id
        ]
        story.knowledge.character_facts.append(fact)
        story.knowledge.character_facts.sort(
            key=lambda item: (item.valid_from_chapter, item.character_id, item.fact_type)
        )
        return fact

    def delete_confirmed(self, story: Story, fact_id: str) -> bool:
        before = len(story.knowledge.character_facts)
        story.knowledge.character_facts = [
            fact
            for fact in story.knowledge.character_facts
            if not (fact.id == fact_id and fact.user_confirmed)
        ]
        return len(story.knowledge.character_facts) < before

    def facts_at(self, story: Story, chapter_index: int) -> list[CharacterFact]:
        visible = [
            fact
            for fact in story.knowledge.character_facts
            if fact.valid_from_chapter <= chapter_index
            and (fact.valid_until_chapter is None or fact.valid_until_chapter >= chapter_index)
        ]
        confirmed_keys = {self._precedence_key(fact) for fact in visible if fact.user_confirmed}
        return [
            fact
            for fact in visible
            if fact.user_confirmed or self._precedence_key(fact) not in confirmed_keys
        ]

    def format_context(self, story: Story, chapter_index: int) -> str:
        facts = self.facts_at(story, chapter_index)
        if not facts:
            return ""
        rows = ["人物事实账本（硬事实）:"]
        for fact in facts:
            character = story.design.characters.get(fact.character_id)
            name = character.name if character else fact.character_id
            source = "用户确认" if fact.user_confirmed else f"提取自第{fact.source_chapter}章"
            rows.append(f"- {name} | {fact.fact_type} = {fact.value}（{source}）")
        return "\n".join(rows)

    def _append_temporal(
        self,
        facts: list[CharacterFact],
        character_id: str,
        fact_type: str,
        value: str,
        chapter: int,
    ) -> None:
        previous = next(
            (
                fact
                for fact in reversed(facts)
                if fact.character_id == character_id and fact.fact_type == fact_type
            ),
            None,
        )
        if previous and previous.value == value:
            return
        if previous and previous.valid_until_chapter is None:
            previous.valid_until_chapter = chapter - 1
        facts.append(self._generated(character_id, fact_type, value, chapter))

    def _append_persistent(
        self,
        facts: list[CharacterFact],
        character_id: str,
        fact_type: str,
        value: str,
        chapter: int,
    ) -> None:
        if any(
            fact.character_id == character_id
            and fact.fact_type == fact_type
            and fact.value == value
            for fact in facts
        ):
            return
        facts.append(self._generated(character_id, fact_type, value, chapter))

    def _generated(
        self, character_id: str, fact_type: str, value: str, chapter: int
    ) -> CharacterFact:
        safe_type = fact_type.replace(":", "-")
        value_key = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        return CharacterFact(
            id=f"auto:{character_id}:{safe_type}:ch{chapter}:{value_key}",
            character_id=character_id,
            fact_type=fact_type,
            value=value,
            valid_from_chapter=chapter,
            source_chapter=chapter,
            confidence=0.7,
        )

    def _precedence_key(self, fact: CharacterFact) -> tuple[str, str, str]:
        value_key = fact.value if fact.fact_type == "knowledge" else ""
        return fact.character_id, fact.fact_type, value_key
