"""Character state tracking across chapters."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from novelforge.core.models import Character, CharacterState, Story
from novelforge.core.utils import extract_json, terms
from novelforge.llm.base import LLMClient


class ICharacterStateTracker(ABC):
    """角色状态跟踪器的抽象接口。"""

    @abstractmethod
    def update_state(self, story: Story, chapter_index: int, character_id: str, new_state: CharacterState) -> None:
        """更新指定角色在指定章节的状态，覆盖同一章节的旧状态。"""
        raise NotImplementedError

    @abstractmethod
    def get_current_state(self, story: Story, character_id: str) -> CharacterState | None:
        """获取指定角色的最新状态，无记录时返回 None。"""
        raise NotImplementedError


class CharacterStateTracker(ICharacterStateTracker):
    """角色状态跟踪器，从章节中提取角色的情感、位置、知识等信息，支持 LLM 和规则回退。"""

    # ------------------------------------------------------------------
    # Genre-agnostic signal tables
    # ------------------------------------------------------------------

    # Emotion detection via universal keywords — no genre bias.
    _EMOTION_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
        ("恐惧", ("害怕", "恐惧", "发抖", "畏惧", "惊恐", "战栗", "afraid", "fear", "terrified")),
        ("愤怒", ("愤怒", "怒火", "咬牙", "暴怒", "愤", "angry", "furious", "rage")),
        ("兴奋", ("高兴", "兴奋", "激动", "狂喜", "欢呼", "excited", "joy", "thrilled")),
        ("悲伤", ("悲伤", "哀伤", "哭泣", "泪", "心痛", "sad", "grief", "cry", "sorrow")),
        ("冷静", ("冷静", "镇定", "沉着", "平静", "淡漠", "calm", "composed")),
        ("焦虑", ("担心", "焦虑", "不安", "忐忑", "worry", "anxious", "nervous")),
        ("坚定", ("坚定", "决心", "毅然", "誓", "determined", "resolute", "resolve")),
        ("困惑", ("困惑", "迷茫", "不解", "疑惑", "confused", "puzzled", "lost")),
    ]

    # Location detection — look for words near location markers.
    _LOCATION_MARKERS: tuple[str, ...] = (
        "在", "去", "来到", "进入", "离开", "穿过", "前往", "返回",
        "抵达", "到达", "at", "enter", "leave", "arrive",
    )

    # Common location-type words that appear across genres.
    _LOCATION_PATTERNS: tuple[str, ...] = (
        # Indoor
        "房间", "大厅", "走廊", "地下室", "阁楼", "办公室", "客厅", "卧室",
        "room", "hall", "corridor", "office", "house",
        # Outdoor
        "森林", "山", "河", "湖", "海", "沙漠", "草原", "街道", "广场", "桥",
        "forest", "mountain", "river", "lake", "sea", "street", "bridge", "field",
        # Institutional / genre-spanning
        "学校", "医院", "寺庙", "宫殿", "酒馆", "客栈", "飞船", "基地", "塔",
        "球场", "训练场", "擂台", "竞技场", "赛场", "武馆", "道场",
        "school", "hospital", "temple", "palace", "tavern", "ship", "base", "tower",
        "arena", "stadium", "gym", "dojo",
    )

    # Knowledge-gain signal words.
    _KNOWLEDGE_SIGNALS: tuple[str, ...] = (
        "发现", "知道", "明白", "意识到", "真相", "学会", "领悟", "掌握",
        "discover", "learn", "realize", "understand", "find out",
    )

    _EMOTION_DEFAULT = "紧张"

    def __init__(self, llm: LLMClient | None = None) -> None:
        """初始化角色状态跟踪器。

        Args:
            llm: 可选的 LLM 客户端，为 None 时使用规则回退。
        """
        self.llm = llm

    def update_state(self, story: Story, chapter_index: int, character_id: str, new_state: CharacterState) -> None:
        """更新或覆盖指定角色在指定章节的状态快照。"""
        states = [state for state in story.memory.states.get(character_id, []) if state.chapter != chapter_index]
        states.append(new_state)
        states.sort(key=lambda item: item.chapter)
        story.memory.states[character_id] = states

    def get_current_state(self, story: Story, character_id: str) -> CharacterState | None:
        """返回该角色章节编号最大的状态，无记录时返回 None。"""
        states = story.memory.states.get(character_id, [])
        return max(states, key=lambda item: item.chapter) if states else None

    def extract_state_from_chapter(self, story: Story, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        """从章节内容提取角色状态，写入 story 并返回状态列表。优先 LLM，失败回退到规则。"""
        states = self._llm_extract(chapter_index, content, characters) if self.llm else []
        if not states:
            states = self._rule_extract(chapter_index, content, characters)
        for state in states:
            self.update_state(story, chapter_index, state.character_id, state)
        return states

    def check_consistency(self, state_before: CharacterState | None, state_after: CharacterState) -> list[str]:
        """对比前后两个状态，检测位置跳变和情绪极端反转等问题，返回问题列表。"""
        if state_before is None:
            return []
        issues: list[str] = []

        # Location change without transition record.
        if state_before.location and state_after.location and state_before.location != state_after.location:
            if not state_after.knowledge_gained:
                distance = state_after.chapter - state_before.chapter
                issues.append(
                    f"{state_after.character_id} 从 {state_before.location} 到 {state_after.location}"
                    f"（跨{distance}章），缺少位置转移说明。"
                )

        # Extreme emotion flip without relationship change.
        opposite_pairs = (
            ("恐惧", "兴奋"), ("悲伤", "狂喜"), ("敌对", "亲密"),
            ("恐惧", "坚定"), ("绝望", "希望"),
        )
        for before, after in opposite_pairs:
            if before in state_before.emotional_state and after in state_after.emotional_state:
                if not state_after.relationship_changes:
                    issues.append(
                        f"{state_after.character_id} 情绪从 {before} 到 {after}，需要过渡或原因。"
                    )

        # Generic continuity check: if the character previously gained knowledge
        # about a weakness/limitation, check for sudden unexplained contradiction.
        for knowledge in state_before.knowledge_gained:
            self._check_knowledge_contradiction(
                knowledge, state_after, state_after.character_id, issues
            )

        return issues

    def _check_knowledge_contradiction(
        self,
        knowledge: str,
        state_after: CharacterState,
        character_id: str,
        issues: list[str],
    ) -> None:
        """检测知识获取与后续状态的矛盾（通用版）。"""
        # Look for fear/weakness patterns in knowledge
        weakness_signals = ("怕", "恐惧", "畏惧", "弱点", "不能", "无法", "fear", "weakness", "cannot")
        for signal in weakness_signals:
            if signal in knowledge:
                # Check if the character enters a scenario related to that weakness
                # without an "overcome" signal
                overcome_signals = ("克服", "战胜", "适应", "不再", "overcome", "conquer", "adapt")
                if state_after.location and not any(s in " ".join(state_after.knowledge_gained) for s in overcome_signals):
                    if signal not in state_after.emotional_state:
                        short_knowledge = knowledge[:20]
                        issues.append(
                            f"{character_id} 曾被记录为有[{short_knowledge}]，"
                            f"但本章状态中缺少克服或应对该限制的过渡。"
                        )
                return

    def _llm_extract(self, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        """调用 LLM 从章节中提取角色状态，返回 CharacterState 列表。"""
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
            data = json.loads(extract_json(raw))
            return [CharacterState.model_validate(item) for item in data if item.get("character_id")]
        except Exception:
            return []

    def _rule_extract(self, chapter_index: int, content: str, characters: list[Character]) -> list[CharacterState]:
        """不依赖 LLM 的规则提取：猜测每个角色的情感、位置和知识获取。"""
        if not characters:
            names = sorted(set(re.findall(r"[一-鿿]{2,4}", content)))[:1]
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
        """基于通用情绪关键词匹配猜测角色的情感状态。"""
        for emotion, signals in self._EMOTION_SIGNALS:
            if any(signal in content for signal in signals):
                return emotion
        return self._EMOTION_DEFAULT

    def _guess_location(self, content: str) -> str:
        """基于通用位置模式匹配猜测角色所在位置。"""
        for pattern in self._LOCATION_PATTERNS:
            if pattern in content:
                return pattern
        return "未知地点"

    def _guess_knowledge(self, content: str) -> list[str]:
        """基于通用知识获取信号词判断角色是否在本章获得了新知识。"""
        gains = []
        for marker in self._KNOWLEDGE_SIGNALS:
            if marker in content:
                gains.append(f"本章{marker}了关键信息")
                break
        return gains
