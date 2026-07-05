"""Planning agent for outlines and scene beats."""

from __future__ import annotations

from novelforge.agents.base import BaseAgent
from novelforge.core.models import Beat, ChapterOutline


class PlannerAgent(BaseAgent):
    name = "planner"

    def generate_outline(self, premise: str, num_chapters: int) -> list[ChapterOutline]:
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

    def adjust_structure(self, feedback: str) -> str:
        system = "你是结构编辑。请根据反馈给出大纲调整建议。"
        return self._chat(system, feedback)
