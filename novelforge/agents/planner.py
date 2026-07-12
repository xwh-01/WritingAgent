"""Planning agent for outlines and scene beats."""

from __future__ import annotations

from novelforge.agents.base import BaseAgent
from novelforge.core.models import Beat, ChapterContract, ChapterOutline, Story


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

    def generate_beats(self, chapter_outline: ChapterOutline, context: str = "") -> list[Beat]:
        """为给定章节大纲生成 3-5 个场景节拍，失败时返回默认节拍。"""
        system = (
            "你是小说分场设计师。请严格输出 JSON 数组，每个元素符合 Beat: "
            "{scene_index:int,description:str,goal:str,outcome:str}。"
        )
        user = (
            "generate_beats: 为以下章节大纲生成 3 到 5 个场景节拍。\n"
            f"章节大纲: {chapter_outline.model_dump_json()}\n"
            f"上下文: {context[:3000]}\n只输出 JSON。"
        )
        try:
            return self._parse_model_list(self._chat(system, user), Beat)
        except Exception:
            return [
                Beat(scene_index=1, description="开场展示压力与目标。", goal="明确主角要解决的问题。", outcome="主角被迫行动。"),
                Beat(scene_index=2, description="中段遭遇阻碍与选择。", goal="推动冲突升级。", outcome="获得线索但付出代价。"),
                Beat(scene_index=3, description="结尾形成转折或悬念。", goal="完成本章推进。", outcome="新的危险浮现。"),
            ]

    def generate_chapter_contract(self, story: Story, chapter_outline: ChapterOutline) -> ChapterContract:
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
            f"当前故事线: {story.memory.story_bible.active_threads}\n"
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
                active_threads=list(story.memory.story_bible.active_threads),
                style_requirements=[story.style_guide] if story.style_guide else [],
                notes=f"核心冲突：{chapter_outline.conflict}",
            )

    def adjust_structure(self, feedback: str) -> str:
        """根据反馈返回大纲结构调整建议。"""
        system = "你是结构编辑。请根据反馈给出大纲调整建议。"
        return self._chat(system, feedback)
