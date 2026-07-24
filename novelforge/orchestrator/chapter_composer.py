"""Scene-based chapter planning and composition."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from novelforge.core.exceptions import WorkflowError
from novelforge.core.generation_budget import GenerationBudgetExceeded
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    ContractEvidenceLedger,
    SceneEndState,
    ScenePatch,
    Story,
    content_digest,
)
from novelforge.validation import ContractObligationCompiler

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

    def __init__(
        self,
        planner,
        writer,
        target_length: int,
        scene_context_builder: Any | None = None,
        obligation_compiler: ContractObligationCompiler | None = None,
        editor: Any | None = None,
    ) -> None:
        self.planner = planner
        self.writer = writer
        self.target_length = target_length
        self.scene_context_builder = scene_context_builder
        self.obligation_compiler = obligation_compiler or ContractObligationCompiler()
        self.editor = editor

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
            beats = self.planner.generate_beats(
                outline,
                context,
                story=story,
                contract=contract,
                previous_chapter_summary=previous_summary,
                character_states=states,
                style_requirements=story.style_guide,
                target_length=self.target_length,
            )
            plan = self.obligation_compiler.compile(contract, beats)
            if not plan.is_executable:
                messages = "; ".join(item.message for item in plan.conflicts)
                raise WorkflowError(f"Chapter contract is not executable: {messages}")
            for scene in beats:
                scene.contract_obligations = [
                    item.model_dump(mode="json")
                    for item in plan.obligations_for_scene(scene.scene_index)
                ]
            return beats
        except GenerationBudgetExceeded:
            raise
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

        execution_plan = self.obligation_compiler.compile(contract, candidate.beats)
        if not execution_plan.is_executable:
            messages = "; ".join(item.message for item in execution_plan.conflicts)
            raise WorkflowError(f"Chapter contract is not executable: {messages}")
        for scene in candidate.beats:
            scene.contract_obligations = [
                item.model_dump(mode="json")
                for item in execution_plan.obligations_for_scene(scene.scene_index)
            ]

        previous_end: SceneEndState | None = None
        completed_obligations: list[dict] = []
        # Contract exclusions are carried once, in each scene's explicit
        # HARD_EXCLUSIONS packet. Keep this list for writer-wide style and
        # transition guardrails only, rather than repeating the contract.
        forbidden = [*self.DEFAULT_FORBIDDEN_ACTIONS]
        for scene in sorted(candidate.beats, key=lambda item: item.scene_index):
            try:
                constraints = self.validate_transition(previous_end, scene)
                character_states = self.scene_character_states(
                    story,
                    scene,
                    outline.chapter_index,
                )
                scene_context = ""
                if self.scene_context_builder is not None:
                    packet = self.scene_context_builder.build_scene_context(
                        outline.chapter_index,
                        story,
                        scene,
                    )
                    scene_context = packet.content
                draft = self.writer.write_scene(
                    story_premise=story.premise,
                    contract=contract,
                    scene=scene,
                    previous_scene_end_state=previous_end,
                    character_states=character_states,
                    style_requirements=story.style_guide,
                    forbidden_actions=forbidden,
                    transition_constraints=constraints,
                    scene_context=scene_context,
                    scene_obligations=scene.contract_obligations,
                    previous_scene_obligations=completed_obligations,
                )
                polished = polish_draft(
                    story,
                    outline.chapter_index,
                    draft.content,
                )
                scene.content = polished
                final_end_state = draft.ending_state
                if polished.strip() != draft.content.strip():
                    final_end_state = self.writer.reconcile_scene_end_state(
                        content=polished,
                        scene=scene,
                        previous_scene_end_state=previous_end,
                    )
                scene.end_state = final_end_state.model_dump()
                scene.status = "completed"
                previous_end = final_end_state
                completed_obligations.extend(
                    item
                    for item in scene.contract_obligations
                    if item.get("mode") in {"must_include", "must_end_with", "must_show_source"}
                )
            except GenerationBudgetExceeded:
                raise
            except Exception as exc:
                raise WorkflowError(f"Scene {scene.scene_index} generation failed: {exc}") from exc

        candidate.sync_content_from_scenes()
        candidate.status = "draft"
        candidate.summary = outline.summary
        return candidate

    def apply_scene_patches(
        self,
        candidate: Chapter,
        patches: list[ScenePatch],
    ) -> Chapter:
        """Apply generated scene edits and refresh each changed scene hand-off.

        Scene prose is the canonical source.  This method is deliberately the
        only mutation entry point used by generation repairs and quality search:
        it protects against stale asynchronous edits and ensures the assembled
        chapter cache can never drift from its scene content.
        """
        if not patches:
            return candidate
        working = candidate.model_copy(deep=True)
        by_index = {scene.scene_index: scene for scene in working.beats}
        for patch in sorted(patches, key=lambda item: item.scene_index):
            scene = by_index.get(patch.scene_index)
            if scene is None:
                raise WorkflowError(f"Scene patch targets unknown scene {patch.scene_index}.")
            end_state = patch.ending_state
            if end_state is None:
                previous = self._previous_scene_end_state(working, scene.scene_index)
                reconcile = getattr(self.writer, "reconcile_scene_end_state", None)
                if callable(reconcile):
                    end_state = reconcile(
                        content=patch.content,
                        scene=scene,
                        previous_scene_end_state=previous,
                    )
                else:
                    end_state = SceneEndState(
                        characters_present=list(scene.participating_characters)
                    )
            try:
                # Apply in scene order so the next patch reconciles against the
                # already-updated hand-off rather than a stale predecessor.
                working.apply_scene_patches([patch.model_copy(update={"ending_state": end_state})])
            except ValueError as exc:
                raise WorkflowError(f"Unable to apply scene patch: {exc}") from exc
        return working

    def generate_scene_quality_patches(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        candidate: Chapter,
        scene_indexes: list[int],
        *,
        variants_per_scene: int = 2,
    ) -> dict[int, list[ScenePatch]]:
        """Draft expressive alternatives only for explicitly risk-ranked scenes.

        The current scene remains a candidate; this method returns at most
        ``variants_per_scene - 1`` replacement patches per selected scene.  It
        never touches lower-risk scenes, which keeps the search bounded and
        preserves their prose byte-for-byte.
        """
        alternatives: dict[int, list[ScenePatch]] = {}
        by_index = {item.scene_index: item for item in candidate.beats}
        for scene_index in scene_indexes:
            scene = by_index.get(scene_index)
            if scene is None or not scene.content.strip():
                continue
            previous = self._previous_scene_end_state(candidate, scene_index)
            constraints = self.validate_transition(previous, scene)
            character_states = self.scene_character_states(story, scene, outline.chapter_index)
            scene_context = ""
            if self.scene_context_builder is not None:
                scene_context = self.scene_context_builder.build_scene_context(
                    outline.chapter_index, story, scene
                ).content
            previous_obligations = [
                item
                for prior in candidate.beats
                if prior.scene_index < scene_index
                for item in prior.contract_obligations
                if item.get("mode") in {"must_include", "must_end_with", "must_show_source"}
            ]
            patches: list[ScenePatch] = []
            for variant in range(1, max(1, variants_per_scene)):
                try:
                    draft = self.writer.write_scene(
                        story_premise=story.premise,
                        contract=contract,
                        scene=scene,
                        previous_scene_end_state=previous,
                        character_states=character_states,
                        style_requirements=story.style_guide,
                        forbidden_actions=[*self.DEFAULT_FORBIDDEN_ACTIONS],
                        transition_constraints=constraints,
                        scene_context=scene_context,
                        scene_obligations=scene.contract_obligations,
                        previous_scene_obligations=previous_obligations,
                        temperature=min(0.7, 0.45 + variant * 0.1),
                        variant_focus=(
                            "加强具体动作、感官细节、潜台词和段落节奏；"
                            "让冲突与代价更可感，但不要增加事件"
                        ),
                    )
                except GenerationBudgetExceeded:
                    raise
                except Exception:
                    # Quality exploration is optional. A malformed alternate
                    # must never discard a contract-compliant current scene.
                    continue
                if draft.content.strip() and draft.content.strip() != scene.content.strip():
                    patches.append(
                        ScenePatch(
                            scene_index=scene_index,
                            content=draft.content.strip(),
                            ending_state=draft.ending_state,
                            reason="risk_quality_search",
                            source_content_digest=content_digest(scene.content),
                        )
                    )
            if patches:
                alternatives[scene_index] = patches
        return alternatives

    def repair_contract_failures(
        self,
        story: Story,
        candidate: Chapter,
        ledger: ContractEvidenceLedger,
    ) -> Chapter:
        """Apply evidence-driven edits only to scenes assigned failing obligations."""
        repair_patch = getattr(self.editor, "revise_scene_patch_from_contract_evidence", None)
        repair = getattr(self.editor, "revise_scene_from_contract_evidence", None)
        if (not callable(repair_patch) and not callable(repair)) or not candidate.beats:
            return candidate
        failed_by_scene: dict[int, list[dict]] = {}
        for entry in ledger.failed_entries:
            failed_by_scene.setdefault(entry.scene_index, []).append(entry.model_dump(mode="json"))
        if not failed_by_scene:
            return candidate

        patches: list[ScenePatch] = []
        for scene in sorted(candidate.beats, key=lambda item: item.scene_index):
            failures = failed_by_scene.get(scene.scene_index, [])
            if failures:
                patch = (
                    repair_patch(scene, failures, story.style_guide)
                    if callable(repair_patch)
                    else None
                )
                if patch is not None:
                    patches.append(
                        patch.model_copy(
                            update={"source_content_digest": content_digest(scene.content)}
                        )
                    )
                    continue
                if callable(repair_patch):
                    # Product editors use the ScenePatch protocol exclusively.
                    # The legacy prose-only method remains for third-party
                    # integrations that have not implemented it yet.
                    continue
                if not callable(repair):
                    continue
                revised = repair(
                    scene.content,
                    scene.contract_obligations,
                    failures,
                    story.style_guide,
                ).strip()
                if revised and revised != scene.content.strip():
                    patches.append(
                        ScenePatch(
                            scene_index=scene.scene_index,
                            content=revised,
                            reason="contract_evidence_repair",
                            source_content_digest=content_digest(scene.content),
                        )
                    )
        return self.apply_scene_patches(candidate, patches) if patches else candidate

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

    @staticmethod
    def _previous_scene_end_state(
        candidate: Chapter,
        scene_index: int,
    ) -> SceneEndState | None:
        previous = [item for item in candidate.beats if item.scene_index < scene_index]
        if not previous:
            return None
        state = sorted(previous, key=lambda item: item.scene_index)[-1].end_state
        return SceneEndState.model_validate(state or {})

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
