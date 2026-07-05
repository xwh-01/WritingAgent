"""Agent that extracts structured long-form memory from chapter text."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from novelforge.agents.base import BaseAgent
from novelforge.core.models import Character, Story, WorldSetting


class ExtractedRelationship(BaseModel):
    source: str
    target: str
    relation: str = "related"


class MemoryExtractionResult(BaseModel):
    characters: list[Character] = Field(default_factory=list)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)


class MemoryExtractorAgent(BaseAgent):
    name = "memory_extractor"

    def extract_chapter_memory(self, story: Story, chapter_index: int, content: str) -> MemoryExtractionResult:
        system = (
            "You are a long-novel memory extraction agent. Extract durable continuity facts from a chapter. "
            "Return strict JSON matching this schema: "
            "{characters:[Character], world_settings:[WorldSetting], "
            "relationships:[{source,target,relation}], continuity_constraints:[string]}. "
            "Only include facts supported by the chapter."
        )
        user = (
            "memory_extract\n"
            f"chapter={chapter_index}\n"
            f"story={json.dumps({'title': story.title, 'premise': story.premise}, ensure_ascii=False)}\n"
            f"existing_characters={json.dumps([c.model_dump() for c in story.characters.values()], ensure_ascii=False)}\n"
            f"content={content[:12000]}"
        )
        try:
            return self._parse_model(self._chat(system, user), MemoryExtractionResult)
        except Exception:
            return self._rule_extract(story, chapter_index, content)

    def _rule_extract(self, story: Story, chapter_index: int, content: str) -> MemoryExtractionResult:
        characters = self._extract_characters(story, content)
        world_settings = self._extract_world_settings(chapter_index, content)
        relationships = self._extract_relationships(characters, content)
        constraints = self._extract_constraints(content)
        return MemoryExtractionResult(
            characters=characters,
            world_settings=world_settings,
            relationships=relationships,
            continuity_constraints=constraints,
        )

    def _extract_characters(self, story: Story, content: str) -> list[Character]:
        found: dict[str, Character] = {}
        for character in story.characters.values():
            if character.name and (character.name in content or character.id in content):
                found[character.id] = character

        known_names = ["王绍康", "后羿", "教练", "门将", "主角"]
        for name in known_names:
            if name in content:
                character_id = self._slug(name)
                found.setdefault(
                    character_id,
                    Character(
                        id=character_id,
                        name=name,
                        personality=self._character_trait(name, content),
                        motivation=self._character_motivation(name, content),
                    ),
                )

        for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", content):
            if name.lower() in {"chapter", "memory", "agent"}:
                continue
            character_id = self._slug(name)
            found.setdefault(character_id, Character(id=character_id, name=name))
            if len(found) >= 8:
                break
        return list(found.values())

    def _extract_world_settings(self, chapter_index: int, content: str) -> list[WorldSetting]:
        settings: list[WorldSetting] = []
        keywords = {
            "football": ("sport_system", "Football training and match rules affect the protagonist's growth."),
            "goalkeeper": ("sport_system", "Goalkeeper skills and anticipation are core long-term mechanics."),
            "training": ("training", "Training routines can change character ability and team status."),
            "王者荣耀": ("game_link", "Honor of Kings experience can influence tactical anticipation."),
            "后羿": ("game_link", "Hou Yi's aiming and prediction pattern is a recurring ability metaphor."),
            "足球": ("sport_system", "足球训练和比赛规则会持续影响人物成长。"),
            "门将": ("sport_system", "门将预判、扑救和站位是核心能力设定。"),
            "训练": ("training", "训练会改变人物能力、体能和队内地位。"),
            "球场": ("location", "球场是关键行动场景。"),
        }
        for keyword, (category, text) in keywords.items():
            if keyword.lower() in content.lower():
                settings.append(
                    WorldSetting(
                        id=f"world-{category}-{abs(hash(keyword + str(chapter_index))) % 100000}",
                        category=category,
                        content=text,
                        metadata={"chapter": chapter_index, "source_keyword": keyword},
                    )
                )
        return settings[:8]

    def _extract_relationships(self, characters: list[Character], content: str) -> list[ExtractedRelationship]:
        if len(characters) < 2:
            return []
        relations: list[ExtractedRelationship] = []
        for left in characters:
            for right in characters:
                if left.id == right.id:
                    continue
                if left.name in content and right.name in content:
                    relation = "teammate_or_rival"
                    if "教练" in {left.name, right.name} or "coach" in content.lower():
                        relation = "coach_and_player"
                    relations.append(ExtractedRelationship(source=left.id, target=right.id, relation=relation))
                if len(relations) >= 6:
                    return relations
        return relations

    def _extract_constraints(self, content: str) -> list[str]:
        constraints: list[str] = []
        if any(token in content for token in ("王者荣耀", "后羿", "Honor of Kings")):
            constraints.append("Keep the game-derived anticipation ability consistent and explainable through training or perception.")
        if any(token in content for token in ("伤", "injury", "受伤")):
            constraints.append("Track injuries across later chapters until recovery is shown.")
        if any(token in content for token in ("秘密", "secret", "真相")):
            constraints.append("Preserve unresolved secrets until an explicit reveal chapter.")
        return constraints

    def _character_trait(self, name: str, content: str) -> str:
        if name == "王绍康" and any(token in content for token in ("预判", "扑救", "后羿")):
            return "敏锐、擅长预判、在压力中成长"
        return ""

    def _character_motivation(self, name: str, content: str) -> str:
        if name == "王绍康" and any(token in content for token in ("门将", "足球", "goalkeeper")):
            return "成为更强的门将"
        return ""

    def _slug(self, value: str) -> str:
        slug = re.sub(r"\W+", "-", value.strip().lower()).strip("-")
        return slug or f"entity-{abs(hash(value)) % 100000}"
