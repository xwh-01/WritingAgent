"""Planning agent for outlines and scene beats."""

from __future__ import annotations

from novelforge.agents.base import BaseAgent
from novelforge.domain import Beat, ChapterContract, ChapterOutline, Story


class PlannerAgent(BaseAgent):
    """规划 Agent，生成章节大纲与场景节拍。"""

    name = "planner"

    def generate_outline(self, premise: str, num_chapters: int) -> list[ChapterOutline]:
        """根据故事前提生成指定数量的章节大纲，失败时返回规则兜底。"""
        system = (
            "你是专业长篇小说规划师。请严格输出 JSON 数组，每个元素符合 ChapterOutline: "
            "{chapter_index:int,title:str,summary:str,conflict:str,pov_character:str|null}。"
        )
        user = (
            f"generate_outline: 根据以下故事前提生成 {num_chapters} 章章节大纲。\n"
            f"故事前提: {premise}\n"
            "只输出 JSON，不要解释。"
        )
        try:
            return self._parse_model_list(self._chat(system, user), ChapterOutline)
        except Exception:
            return [
                ChapterOutline(
                    chapter_index=i,
                    title=f"第{i}章",
                    summary=f"围绕故事前提推进第{i}个关键事件。",
                    conflict="主角目标与外部阻力发生碰撞。",
                    pov_character="主角",
                )
                for i in range(1, num_chapters + 1)
            ]

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
            "最后一场必须兑现章节 ending_hook；target_length 总和应接近章节目标字数。"
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
        beats = self._parse_model_list(self._chat(system, user), Beat)
        if not beats:
            raise ValueError("Planner returned an empty scene plan.")
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

    def generate_chapter_contract(
        self, story: Story, chapter_outline: ChapterOutline
    ) -> ChapterContract:
        """把章节大纲扩展成可编辑、可验收的章节执行合同。"""
        system = (
            "你是小说章节制片人。严格输出 ChapterContract JSON，必须保留大纲目标，"
            "不要擅自增加重大设定。字段包括 chapter_index,pov_character,location,time_context,"
            "must_happen,must_not_happen,character_goals,knowledge_boundaries,active_threads,"
            "ending_hook,style_requirements,notes。"
        )
        user = (
            "generate_chapter_contract\n"
            f"故事前提: {story.premise}\n"
            f"章节大纲: {chapter_outline.model_dump_json()}\n"
            f"当前故事线: {story.knowledge.guide.active_threads}\n"
            f"文风: {story.style_guide}\n只输出 JSON。"
        )
        try:
            contract = self._parse_model(self._chat(system, user), ChapterContract)
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
