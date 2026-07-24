"""Planning agent for outlines and scene beats."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.domain import Beat, ChapterContract, ChapterOutline, Story


class PlannerAgent(BaseAgent):
    """规划 Agent，生成章节大纲与场景节拍。"""

    name = "planner"

    def generate_outline(
        self,
        premise: str,
        num_chapters: int,
        *,
        story: Story | None = None,
        start_chapter: int = 1,
    ) -> list[ChapterOutline]:
        """Generate a new outline slice, grounded in the current novel state.

        Continuations deliberately receive existing outlines, committed progress,
        character arcs and open threads.  A continuation is not a fresh story
        prompt with chapter numbers relabelled afterwards.
        """
        system = (
            "你是专业长篇小说规划师。请严格输出 JSON 数组，每个元素符合 ChapterOutline: "
            "{chapter_index:int,title:str,summary:str,conflict:str,pov_character:str|null}。"
            "续写大纲必须承接既有章节，推进未解决线索和人物弧，不能重置冲突、重复已完成事件，"
            "也不能提前泄露尚未发生的正式正文。"
        )
        continuation = self._outline_continuation_context(story, start_chapter)
        user = (
            f"generate_outline: 从第 {start_chapter} 章开始生成连续的 {num_chapters} 章章节大纲。\n"
            f"故事前提: {premise}\n"
            f"续写上下文: {json.dumps(continuation, ensure_ascii=False)}\n"
            "只输出 JSON，不要解释。"
        )
        try:
            return self._chat_model_list(system, user, ChapterOutline)
        except Exception:
            return [
                ChapterOutline(
                    chapter_index=i,
                    title=f"第{i}章",
                    summary=(
                        f"承接既有故事线，围绕故事前提推进第{i}个关键事件。"
                        if start_chapter == 1
                        else f"承接第{i - 1}章已建立的线索与人物选择，推进第{i}章关键事件。"
                    ),
                    conflict="既有目标与新的外部阻力发生碰撞。",
                    pov_character="主角",
                )
                for i in range(start_chapter, start_chapter + num_chapters)
            ]

    @staticmethod
    def _outline_continuation_context(story: Story | None, start_chapter: int) -> dict:
        if story is None:
            return {"start_chapter": start_chapter}
        summaries = [
            item.model_dump()
            for _, item in sorted(story.knowledge.chapter_summaries.items())[-8:]
        ]
        return {
            "start_chapter": start_chapter,
            "story_status": str(story.status),
            "current_chapter": story.current_chapter,
            "existing_outlines": [item.model_dump() for item in story.design.outlines[-30:]],
            "committed_chapter_summaries": summaries,
            "active_threads": list(story.knowledge.guide.active_threads),
            "pending_foreshadowings": [
                item.model_dump()
                for item in story.knowledge.foreshadowings
                if str(item.status) == "pending"
            ][-15:],
            "character_arcs": [
                {
                    "id": character.id,
                    "name": character.name,
                    "motivation": character.motivation,
                    "weakness": character.weakness,
                    "arc": character.arc,
                }
                for character in story.design.characters.values()
            ],
            "world_rules": [item.model_dump() for item in story.design.world_settings[:20]],
        }

    def generate_beats(
        self,
        chapter_outline: ChapterOutline,
        context: str = "",
        *,
        story: Story | None = None,
        contract: ChapterContract | None = None,
        previous_chapter_summary: str = "",
        character_states: dict | None = None,
        style_requirements: str = "",
        target_length: int = 1800,
    ) -> list[Beat]:
        """Generate the complete ordered, structured scene plan for one chapter."""
        system = (
            "你是小说分场设计师。严格输出一个 JSON 数组，不要输出解释或 Markdown。"
            "每个元素必须是完整场景对象，字段包括 scene_index,title,purpose,pov_character,"
            "location,time_context,participating_characters,character_goals,conflict,obstacle,"
            "must_happen,must_not_happen,information_revealed,start_state,end_state,"
            "transition_to_next,target_length,description,goal,outcome,content,status。"
            "content 必须为空字符串，status 必须为 planned。场景编号从 1 连续递增。"
            "所有场景共同完成章节目标；每场都有不同的独立功能、人物目标、实际阻碍和结果；"
            "相邻场景功能不得相同；前场 end_state 必须支持后场 start_state；"
            "最后一场必须兑现章节 ending_hook；target_length 总和应接近章节目标字数。\n"
            "字段类型：scene_index、target_length 为整数；participating_characters、must_happen、"
            "must_not_happen、information_revealed 为字符串数组；character_goals、start_state、end_state "
            "为对象；其余为字符串。"
        )
        premise = story.premise if story else ""
        user = (
            "generate_beats\n"
            f"故事前提: {premise}\n"
            f"章节目标字数: {target_length}\n"
            f"章节大纲: {chapter_outline.model_dump_json()}\n"
            f"ChapterContract: {contract.model_dump_json() if contract else '{}'}\n"
            f"上一章摘要: {previous_chapter_summary}\n"
            f"相关人物状态: {character_states or {}}\n"
            f"文风要求: {style_requirements}\n"
            f"补充上下文: {context[:3000]}\n"
            "只输出 JSON 数组。"
        )
        beats = self._chat_model_list(system, user, Beat)
        if not beats:
            raise ValueError("Planner returned an empty scene plan.")
        self._normalize_scene_plan(beats, chapter_outline, contract, target_length)
        beats.sort(key=lambda item: item.scene_index)
        expected = list(range(1, len(beats) + 1))
        if [item.scene_index for item in beats] != expected:
            raise ValueError("Scene indexes must be unique and contiguous from 1.")
        for beat in beats:
            if (
                not (beat.purpose or beat.goal)
                or not beat.character_goals
                or not beat.obstacle
                or not beat.outcome
            ):
                raise ValueError(
                    f"Scene {beat.scene_index} lacks purpose, character goals, obstacle, or outcome."
                )
            if beat.target_length <= 0:
                raise ValueError(f"Scene {beat.scene_index} must have a positive target_length.")
            beat.content = ""
            beat.status = "planned"
        purposes = [(item.purpose or item.goal).strip() for item in beats]
        if any(left == right for left, right in zip(purposes, purposes[1:])):
            raise ValueError("Adjacent scenes cannot have the same purpose.")
        planned_length = sum(item.target_length for item in beats)
        tolerance = max(200, int(target_length * 0.25))
        if abs(planned_length - target_length) > tolerance:
            allocated = [
                max(1, round(target_length * item.target_length / planned_length)) for item in beats
            ]
            allocated[-1] += target_length - sum(allocated)
            if allocated[-1] <= 0:
                raise ValueError("Chapter target length is too small for the scene plan.")
            for beat, normalized in zip(beats, allocated, strict=True):
                beat.target_length = normalized
        return beats

    @staticmethod
    def _normalize_scene_plan(
        beats: list[Beat],
        outline: ChapterOutline,
        contract: ChapterContract | None,
        target_length: int,
    ) -> None:
        """Fill harmless missing planning fields without spending a repair call.

        Structured models sometimes emit a syntactically valid beat with empty
        optional strings. These are planning omissions, not evidence that the
        chapter is impossible; the outline and contract already provide safe,
        local defaults. Deliberately supplied non-empty fields are untouched.
        """
        fallback_goal = outline.summary or outline.conflict or "推进本章冲突"
        fallback_obstacle = outline.conflict or (contract.notes if contract else "") or "出现阻力"
        fallback_pov = outline.pov_character or (contract.pov_character if contract else "")
        default_length = max(1, target_length // max(len(beats), 1))
        for position, beat in enumerate(beats, 1):
            if beat.scene_index <= 0:
                beat.scene_index = position
            if not beat.title:
                beat.title = f"场景 {beat.scene_index}"
            if not beat.purpose:
                beat.purpose = fallback_goal
            if not beat.goal:
                beat.goal = beat.purpose
            if not beat.pov_character:
                beat.pov_character = fallback_pov
            if not beat.character_goals:
                actor = beat.pov_character or "主角"
                beat.character_goals = {actor: beat.goal}
            if not beat.obstacle:
                beat.obstacle = fallback_obstacle
            if not beat.conflict:
                beat.conflict = beat.obstacle
            if not beat.outcome:
                beat.outcome = "局面发生可见变化"
            if beat.target_length <= 0:
                beat.target_length = default_length

    def generate_chapter_contract(
        self, story: Story, chapter_outline: ChapterOutline
    ) -> ChapterContract:
        """把章节大纲扩展成可编辑、可验收的章节执行合同。"""
        system = (
            "你是小说章节制片人。严格输出 ChapterContract JSON，必须保留大纲目标，"
            "不要擅自增加重大设定。字段包括 chapter_index,pov_character,location,time_context,"
            "must_happen,must_not_happen,character_goals,knowledge_boundaries,active_threads,"
            "ending_hook,style_requirements,notes。knowledge_boundaries 必须使用稳定的桶结构："
            "{角色:{'已知':[事实],'不应知道':[事实],'可以获得':[事实]}}；"
            "不要把‘知道某事’写成键、把 true 或空列表当作事实。"
        )
        user = (
            "generate_chapter_contract\n"
            f"故事前提: {story.premise}\n"
            f"章节大纲: {chapter_outline.model_dump_json()}\n"
            f"当前故事线: {story.knowledge.guide.active_threads}\n"
            f"文风: {story.style_guide}\n只输出 JSON。"
        )
        try:
            contract = self._chat_model(system, user, ChapterContract)
            contract.chapter_index = chapter_outline.chapter_index
            return contract
        except Exception:
            return ChapterContract(
                chapter_index=chapter_outline.chapter_index,
                pov_character=chapter_outline.pov_character,
                must_happen=[chapter_outline.summary],
                active_threads=list(story.knowledge.guide.active_threads),
                style_requirements=[story.style_guide] if story.style_guide else [],
                notes=f"核心冲突：{chapter_outline.conflict}",
            )

    def adjust_structure(self, feedback: str) -> str:
        """根据反馈返回大纲结构调整建议。"""
        system = "你是结构编辑。请根据反馈给出大纲调整建议。"
        return self._chat(system, feedback)
