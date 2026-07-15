"""Creative writing agent."""

from __future__ import annotations

import json

from novelforge.agents.base import BaseAgent
from novelforge.domain import Beat, ChapterContract, ChapterOutline, SceneDraft, SceneEndState


class WriterAgent(BaseAgent):
    """写作 Agent，负责撰写可直接发布的小说章节正文。"""

    name = "writer"

    def write_scene(
        self,
        *,
        story_premise: str,
        contract: ChapterContract,
        scene: Beat,
        previous_scene_end_state: SceneEndState | None,
        character_states: dict,
        style_requirements: str,
        forbidden_actions: list[str],
        transition_constraints: list[str] | None = None,
    ) -> SceneDraft:
        """Write one scene and return prose plus its structured continuity hand-off."""
        system = (
            self._build_writer_system_prompt(style_requirements)
            + "\n你当前只写一个场景。严格输出 JSON 对象，顶层仅含 content 和 ending_state。"
            "content 是小说正文；ending_state 是结构化对象，必须包含 characters_present,"
            "character_state_changes,relationship_changes,location_changes,time_changes,"
            "knowledge_gained,items_gained,items_lost,injuries_or_conditions,decisions,promises,"
            "questions_created,questions_resolved,ending_state。不得使用字符串切割边界。"
        )
        requirements = [
            "人物有明确目标并遭遇实际阻碍",
            "人物主动选择且选择产生具体结果",
            "结尾必须发生可传递的状态变化",
            "对话只用于冲突、信息推进或人物塑造，并穿插动作",
            "通过动作、环境和对话呈现剧情，不把计划扩写成总结",
            "不重复已知信息，不越过人物知识边界，不新增重大长期设定",
            "不使用模板化结尾",
        ]
        user = "\n\n".join(
            [
                f"STORY_PREMISE\n{story_premise}",
                f"CHAPTER_CONTRACT\n{json.dumps(contract.model_dump(), ensure_ascii=False)}",
                f"CURRENT_SCENE\n{json.dumps(scene.model_dump(exclude={'content', 'status'}), ensure_ascii=False)}",
                "PREVIOUS_SCENE_END_STATE\n"
                + json.dumps(
                    previous_scene_end_state.model_dump() if previous_scene_end_state else {},
                    ensure_ascii=False,
                ),
                f"CHARACTER_STATES\n{json.dumps(character_states, ensure_ascii=False, default=str)}",
                f"STYLE_REQUIREMENTS\n{style_requirements}",
                "FORBIDDEN_ACTIONS\n"
                + json.dumps(
                    forbidden_actions + (transition_constraints or []), ensure_ascii=False
                ),
                "OUTPUT_REQUIREMENTS\n"
                + "\n".join(f"{index}. {item}" for index, item in enumerate(requirements, 1))
                + f"\n目标长度约 {scene.target_length or 600} 字。只输出合法 JSON。",
            ]
        )
        draft = self._parse_model(self._chat(system, user), SceneDraft)
        if not draft.content.strip():
            raise ValueError("Writer returned empty scene content.")
        draft.content = draft.content.strip()
        return draft

    def write_chapter(
        self,
        chapter_index: int,
        outline: ChapterOutline,
        beats: list[Beat],
        assembled_context: str,
        style_guide: str = "",
        contract: ChapterContract | None = None,
    ) -> str:
        """综合大纲、节拍与上下文，撰写完整章节正文。"""
        system = self._build_writer_system_prompt(style_guide)
        user = (
            f"写第 {chapter_index} 章。\n"
            f"章节大纲: {json.dumps(outline.model_dump(), ensure_ascii=False)}\n"
            f"场景节拍: {json.dumps([beat.model_dump() for beat in beats], ensure_ascii=False)}\n"
            f"章节合同（硬约束，禁止忽略）: {json.dumps(contract.model_dump(), ensure_ascii=False) if contract else '未提供'}\n"
            f"上下文: {assembled_context}\n"
            "输出要求：\n"
            "- 只输出小说正文，不要解释创作思路。\n"
            "- 正文应包含完整场景，不要写成提纲或摘要。\n"
            "- 优先写出人物在压力中的具体反应，而不是直接评价人物。\n"
            "- 严格控制句式节奏：短句写动作和紧张，中句写描写和过渡，长句写心理和反思。\n"
        )
        return self._chat(system, user).strip()

    def _build_writer_system_prompt(self, style_guide: str) -> str:
        """构建包含具体写作技术锚点的系统提示词。

        相比通用"写作要求"，这里给出可执行的句式、节奏和结构指引。
        """
        return (
            "你是成熟的长篇小说作家，负责写可直接发布的章节正文。\n\n"
            "## 场景结构（3-5 段一个场景）\n"
            "每个场景按四步推进：\n"
            "1. 状态建立 — 用 2-3 句交代环境、人物位置和当前情绪\n"
            "2. 阻力出现 — 一个外部事件或内部冲突打破平衡\n"
            "3. 角色选择 — 角色必须在两个坏选项之间做出决定，选择伴随可见代价\n"
            "4. 代价显现 — 选择的后果立即以感官细节（疼痛、温度变化、声音变化）呈现\n\n"
            "## 句式节奏（主动交替）\n"
            "- 短句（≤15 字）：用于动作、转折、紧张时刻。每段至少 1 句\n"
            "- 中句（15-35 字）：用于场景描写、人物过渡、信息交代\n"
            "- 长句（35-50 字）：用于内心矛盾、回忆、环境氛围渲染。每段不超过 2 句\n"
            "- 连续 3 句同为短句时，第 4 句必须是中句或长句以打破单调\n\n"
            "## 对话准则\n"
            "- 每段对话不超过 3 轮不被打断——插入一个微动作（如抿嘴、移开视线、拨弄手指）"
            "或环境细节（如窗外车灯闪过）\n"
            "- 对话要有潜台词：角色嘴上说的和心里想的不一致时，用一个身体语言暴露真实想法\n"
            "- 不同角色的说话节奏应有区分：性急者多用短句和打断，沉稳者用完整句子和停顿\n\n"
            "## 描写密度\n"
            "- 每个场景至少包含一种感官细节（温度、气味、声音、触感）——不只靠视觉\n"
            "- 情感不直接命名（不说'他很愤怒'），而是通过身体反应展现"
            "（'他的指节在桌面压出白印'）\n\n"
            "## 章节结尾\n"
            "必须包含以下三者之一，不能以单纯的总结结束：\n"
            "1. 一个未回答的问题 — 角色面临新的未知\n"
            "2. 一个视觉意象 — 一个有象征意味的画面留在读者脑中\n"
            "3. 一个角色微表情变化 — 暗示内心发生了不可逆的改变\n\n"
            f"## 文风指南\n"
            f"{style_guide or '清晰克制，有临场感，动作和心理交织，长篇连载节奏。避免口号和空泛热血。'}\n"
        )
