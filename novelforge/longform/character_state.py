"""Character state tracking across chapters."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from novelforge.core.models import Character, CharacterState, Story
from novelforge.llm.base import LLMClient


class ICharacterStateTracker(ABC):
    @abstractmethod
    def update_state(self, story: Story, chapter_index: int, character_id: str, new_state: CharacterState) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_current_state(self, story: Story, character_id: str) -> CharacterState | None:
        raise NotImplementedError


class CharacterStateTracker(ICharacterStateTracker):
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def update_state(self, story: Story, chapter_index: int, character_id: str, new_state: CharacterState) -> None:
        states = [state for state in story.character_states.get(character_id, []) if state.chapter != chapter_index]
        states.append(new_state)
        states.sort(key=lambda item: item.chapter)
        story.character_states[character_id] = states

    def get_current_state(self, story: Story, character_id: str) -> CharacterState | None:
        states = story.character_states.get(character_id, [])
        return max(states, key=lambda item: item.chapter) if states else None

    def extract_state_from_chapter(self, story: Story, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        states = self._llm_extract(chapter_index, content, characters) if self.llm else []
        if not states:
            states = self._rule_extract(chapter_index, content, characters)
        for state in states:
            self.update_state(story, chapter_index, state.character_id, state)
        return states

    def check_consistency(self, state_before: CharacterState | None, state_after: CharacterState) -> list[str]:
        if state_before is None:
            return []
        issues: list[str] = []
        if state_before.location and state_after.location and state_before.location != state_after.location:
            if not state_after.knowledge_gained and state_after.chapter == state_before.chapter + 1:
                issues.append(f"{state_after.character_id} 从 {state_before.location} 到 {state_after.location}，缺少位置转移说明。")
        opposite_pairs = (("恐惧", "兴奋"), ("悲伤", "狂喜"), ("敌对", "亲密"))
        for before, after in opposite_pairs:
            if before in state_before.emotional_state and after in state_after.emotional_state and not state_after.relationship_changes:
                issues.append(f"{state_after.character_id} 情绪从 {before} 到 {after}，需要过渡或原因。")
        for knowledge in state_before.knowledge_gained:
            if "怕水" in knowledge and state_after.location and "湖" in state_after.location:
                if "克服" not in " ".join(state_after.knowledge_gained) and "恐惧" not in state_after.emotional_state:
                    issues.append(f"{state_after.character_id} 曾被记录为怕水，但本章进入湖相关场景，缺少克服恐惧的过渡。")
        return issues

    def _llm_extract(self, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        if not characters:
            return []
        prompt = (
            "character_state_extract: 从章节中抽取角色状态。严格输出 JSON 数组，"
            "字段: character_id, chapter, emotional_state, location, knowledge_gained, relationship_changes。\n"
            f"chapter={chapter_index}\ncharacters={json.dumps([c.model_dump() for c in characters], ensure_ascii=False)}\n"
            f"content={content[:9000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = json.loads(self._extract_json(raw))
            return [CharacterState.model_validate(item) for item in data if item.get("character_id")]
        except Exception:
            return []

    def _rule_extract(self, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        if not characters:
            names = sorted(set(re.findall(r"[\u4e00-\u9fff]{2,4}", content)))[:1]
            characters = [Character(id=name, name=name) for name in names]
        states: list[CharacterState] = []
        for character in characters:
            if character.name and character.name not in content and character.id not in content:
                continue
            states.append(
                CharacterState(
                    character_id=character.id,
                    chapter=chapter_index,
                    emotional_state=self._guess_emotion(content),
                    location=self._guess_location(content),
                    knowledge_gained=self._guess_knowledge(content),
                )
            )
        return states

    def _guess_emotion(self, content: str) -> str:
        if any(word in content for word in ("害怕", "恐惧", "发抖")):
            return "恐惧"
        if any(word in content for word in ("愤怒", "怒火", "咬牙")):
            return "愤怒"
        if any(word in content for word in ("高兴", "兴奋", "笑")):
            return "兴奋"
        return "紧张"

    def _guess_location(self, content: str) -> str:
        for marker in ("球场", "学校", "城市", "城墙", "湖", "房间", "训练场"):
            if marker in content:
                return marker
        return "未知地点"

    def _guess_knowledge(self, content: str) -> list[str]:
        gains = []
        for marker in ("发现", "知道", "明白", "意识到", "真相"):
            if marker in content:
                gains.append(f"本章{marker}了关键信息")
                break
        return gains

    def _extract_json(self, text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
