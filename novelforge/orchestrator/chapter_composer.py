"""Scene-based chapter planning and composition."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

from novelforge.core.exceptions import WorkflowError
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    SceneEndState,
    Story,
)

PolishDraft = Callable[[Story, int, str], str]


class ChapterComposer:
    """Plan scenes, enforce transitions, and compose an atomic chapter draft."""

    DEFAULT_FORBIDDEN_ACTIONS = (
        "他不知道的是",
        "真正的挑战才刚刚开始",
        "一切都将发生改变",
        "大量空泛心理描写",
        "人物直接解释双方都知道的信息",
        "同一个意思连续重复",
        "只有对话没有动作",
        "只有描写没有剧情推进",
    )

    def __init__(self, planner, writer, target_length: int) -> None:
        self.planner = planner
        self.writer = writer
        self.target_length = target_length

    def plan_scenes(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        context: str,
    ) -> list[Beat]:
        """Plan structured scenes using only history before the target chapter."""
        previous = story.knowledge.chapter_summaries.get(outline.chapter_index - 1)
        previous_summary = ""
        if previous is not None:
            previous_summary = (
                getattr(previous, "chapter_summary", "")
                or getattr(previous, "summary", "")
                or str(previous)
            )
        states = {
            character_id: [
                item.model_dump() for item in history if item.chapter < outline.chapter_index
            ]
            for character_id, history in story.knowledge.character_states.items()
        }
        try:
            return self.planner.generate_beats(
                outline,
                context,
                story=story,
                contract=contract,
                previous_chapter_summary=previous_summary,
                character_states=states,
                style_requirements=story.style_guide,
                target_length=self.target_length,
            )
        except Exception as exc:
            raise WorkflowError(
                f"Scene planning failed for chapter {outline.chapter_index}: {exc}"
            ) from exc

    def compose(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        context: str,
        polish_draft: PolishDraft,
    ) -> Chapter:
        """Generate every scene and return a candidate without mutating the story."""
        existing = story.manuscript.chapters.get(outline.chapter_index)
        candidate = (
            existing.model_copy(deep=True)
            if existing is not None
            else Chapter(index=outline.chapter_index, title=outline.title)
        )
        if not candidate.beats or any(
            not self.is_structured_scene(item) for item in candidate.beats
        ):
            candidate.beats = self.plan_scenes(story, outline, contract, context)
        else:
            candidate.beats = [item.model_copy(deep=True) for item in candidate.beats]

        previous_end: SceneEndState | None = None
        forbidden = [*contract.must_not_happen, *self.DEFAULT_FORBIDDEN_ACTIONS]
        for scene in sorted(candidate.beats, key=lambda item: item.scene_index):
            try:
                constraints = self.validate_transition(previous_end, scene)
                character_states = self.scene_character_states(
                    story,
                    scene,
                    outline.chapter_index,
                )
                draft = self.writer.write_scene(
                    story_premise=story.premise,
                    contract=contract,
                    scene=scene,
                    previous_scene_end_state=previous_end,
                    character_states=character_states,
                    style_requirements=story.style_guide,
                    forbidden_actions=forbidden,
                    transition_constraints=constraints,
                )
                scene.content = polish_draft(
                    story,
                    outline.chapter_index,
                    draft.content,
                )
                scene.end_state = draft.ending_state.model_dump()
                scene.status = "completed"
                previous_end = draft.ending_state
            except Exception as exc:
                raise WorkflowError(f"Scene {scene.scene_index} generation failed: {exc}") from exc

        candidate.content = self.merge_scenes(candidate.beats)
        candidate.status = "draft"
        candidate.summary = outline.summary
        return candidate

    @staticmethod
    def is_structured_scene(scene: Beat) -> bool:
        return bool(
            (scene.purpose or scene.goal)
            and scene.character_goals
            and scene.obstacle
            and scene.outcome
        )

    @staticmethod
    def scene_character_states(
        story: Story,
        scene: Beat,
        chapter_index: int,
    ) -> dict[str, object]:
        names = set(scene.participating_characters)
        if scene.pov_character:
            names.add(scene.pov_character)
        result: dict[str, object] = {}
        for character_id, history in story.knowledge.character_states.items():
            character = story.design.characters.get(character_id)
            if (
                names
                and character_id not in names
                and (character is None or character.name not in names)
            ):
                continue
            visible = [state for state in history if state.chapter < chapter_index]
            if visible:
                result[character_id] = visible[-1].model_dump()
        return result

    @staticmethod
    def merge_scenes(scenes: list[Beat]) -> str:
        ordered = sorted(scenes, key=lambda item: item.scene_index)
        if any(not item.content.strip() for item in ordered):
            raise WorkflowError("Cannot merge chapter because at least one scene has no content.")
        return "\n\n***\n\n".join(item.content.strip() for item in ordered)

    @classmethod
    def validate_transition(
        cls,
        previous: SceneEndState | None,
        current: Beat,
    ) -> list[str]:
        """Reject hard contradictions and return softer carry-over constraints."""
        if previous is None:
            return []
        start = current.start_state or {}
        planned_locations = cls._mapping_from_state(
            start,
            "location_changes",
            "character_locations",
            "locations",
        )
        for character, location in previous.location_changes.items():
            planned = planned_locations.get(character)
            if planned and planned != location:
                raise WorkflowError(
                    f"location conflict for {character}: previous scene ended at "
                    f"{location!r}, scene {current.scene_index} starts at {planned!r}"
                )

        inventories = cls._mapping_from_state(
            start,
            "items",
            "inventory",
            "items_gained",
        )
        for character, lost_items in previous.items_lost.items():
            present = cls._as_string_set(inventories.get(character, []))
            repeated = present.intersection(cls._as_string_set(lost_items))
            if repeated:
                raise WorkflowError(
                    f"lost item conflict for {character}: "
                    f"{', '.join(sorted(repeated))} reappears in "
                    f"scene {current.scene_index}"
                )

        required_knowledge = cls._mapping_from_state(
            start,
            "knowledge_from_previous_scene",
            "newly_acquired_knowledge",
        )
        for character, required in required_knowledge.items():
            available = cls._as_string_set(previous.knowledge_gained.get(character, []))
            unexplained = cls._as_string_set(required).difference(available)
            if unexplained:
                raise WorkflowError(
                    f"knowledge conflict for {character}: "
                    f"{', '.join(sorted(unexplained))} was not acquired "
                    f"before scene {current.scene_index}"
                )

        planned_time = str(start.get("time_context") or start.get("time") or "")
        if (
            previous.time_changes
            and planned_time
            and cls._time_is_earlier(planned_time, previous.time_changes)
        ):
            raise WorkflowError(
                f"time conflict: previous scene ended at {previous.time_changes!r}, "
                f"scene {current.scene_index} starts at {planned_time!r}"
            )

        constraints: list[str] = []
        if previous.decisions:
            constraints.append(
                "承接上一场景决定: " + json.dumps(previous.decisions, ensure_ascii=False)
            )
        if previous.promises:
            constraints.append("不得遗忘上一场景承诺: " + "；".join(previous.promises))
        if previous.knowledge_gained:
            constraints.append(
                "人物知识边界已增加: " + json.dumps(previous.knowledge_gained, ensure_ascii=False)
            )
        if previous.items_lost:
            constraints.append(
                "已丢失物品不得无解释出现: " + json.dumps(previous.items_lost, ensure_ascii=False)
            )
        return constraints

    @staticmethod
    def _mapping_from_state(state: dict, *keys: str) -> dict:
        for key in keys:
            value = state.get(key)
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _as_string_set(value: object) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, (list, tuple, set)):
            return {str(item) for item in value}
        return set()

    @staticmethod
    def _time_is_earlier(current: str, previous: str) -> bool:
        def parse(value: str) -> datetime | None:
            normalized = value.strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return None

        current_dt, previous_dt = parse(current), parse(previous)
        return bool(current_dt and previous_dt and current_dt < previous_dt)
