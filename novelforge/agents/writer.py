"""Creative writing agent."""

from __future__ import annotations

import json
import re

from novelforge.agents.base import BaseAgent
from novelforge.core.utils import extract_json
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
        scene_context: str = "",
        scene_obligations: list[dict] | None = None,
        previous_scene_obligations: list[dict] | None = None,
        temperature: float | None = None,
        variant_focus: str = "",
    ) -> SceneDraft:
        """Write one scene and return prose plus its structured continuity hand-off."""
        exclusions = [
            str(item.get("requirement", "")).strip()
            for item in (scene_obligations or [])
            if item.get("mode") == "must_exclude" and str(item.get("requirement", "")).strip()
        ]
        executable_obligations = [
            item for item in (scene_obligations or []) if item.get("mode") != "must_exclude"
        ]
        execution_checklist = [
            {
                "id": str(item.get("id", "")),
                "mode": str(item.get("mode", "must_include")),
                "requirement": str(item.get("requirement", "")).strip(),
            }
            for item in executable_obligations
            if str(item.get("requirement", "")).strip()
        ]
        previous_requirements = [
            str(item.get("requirement", "")).strip()
            for item in (previous_scene_obligations or [])
            if str(item.get("requirement", "")).strip()
        ]
        negative_conditions = [
            requirement
            for requirement in contract.must_happen
            if any(marker in requirement for marker in ("没有", "不得", "不能", "未"))
        ]
        unresolved_choice_exclusions = [
            item
            for item in exclusions
            if any(marker in item for marker in ("最终决定", "明确选择", "播出或封存"))
        ]
        system = (
            "你是长篇小说作者，只写当前场景。以动作、环境和对话推进冲突；人物必须做选择并付出"
            "可见代价。不要解释创作思路、不要提前写未来场景、不要重复上一场已完成的事件。"
            "不得凭空新增有名字的人物、地点、组织、历史事件、魔法规则、物件机制、数值期限或角色背景；"
            "只有 SCENE_BRIEF、场景上下文、前序状态和合同义务中明示的事实才能写成确定事实。"
            "优先输出 JSON 对象 {content, ending_state}；若无法稳定输出 JSON，只输出完整场景正文。"
        )
        if exclusions:
            system += (
                "\nHARD_EXCLUSIONS: "
                + json.dumps(exclusions, ensure_ascii=False)
                + "。绝不能把禁项本身写成已经发生的行动、结果或事实。"
                "只有当禁项明确禁止意图、准备、提议、命令、威胁或暗示时，才禁止那些前置行为；"
                "否则必须区分实际完成的行为与尚未执行的准备。若本场结尾义务明确要求出现未启用的工具、"
                "停住的动作或犹豫，应保留该义务而不能误写成禁项已经发生。"
            )
            if any("全部细节" in item or "全貌" in item for item in exclusions):
                system += (
                    " 若禁项禁止披露‘全部细节’或‘全貌’，正文只能提及线索名称；"
                    "不得引用原文、条款、数字、日期、住址、当事人、任务内容或报告正文。"
                )
        if negative_conditions:
            system += (
                "\nNEGATIVE_CONDITIONS: "
                + json.dumps(negative_conditions, ensure_ascii=False)
                + "。这些是必需事件中的否定部分，必须原样保持；不能把‘没有/不得/不能/未’写成相反结果。"
            )
        if execution_checklist:
            system += (
                "\nCONTRACT_EXECUTION_CHECKLIST: "
                + json.dumps(execution_checklist, ensure_ascii=False)
                + "。这是本场景离开前必须逐条完成的硬性清单。每一项都要在正文中留下可独立引用的"
                "人物、动作、对象或可见结果证据；不得只写提纲、意图或模糊同义暗示。"
                "写完后自行逐项核对，再输出正文；不要在正文中展示这份清单或解释核对过程。"
                " 每条义务中的命名人物、关键物件、目的地/记录载体和不可逆动作都是合同锚点："
                "正文必须至少明确写出一次，不能只用‘他’、‘窗口’、‘装置’等泛称替代，也不能把因果结果"
                "写成尚未发生的意图。"
            )
        if unresolved_choice_exclusions:
            system += (
                "\nUNRESOLVED_CHOICE_GUARD: "
                + json.dumps(unresolved_choice_exclusions, ensure_ascii=False)
                + "。这些禁项要求人物尚未作出最终选择。只能写身体停顿、未解压力或仍在权衡的选项；"
                "不得写‘决定/选择/放弃/封存/播出/不按下/不再’或任何表明已选定一边的结论。"
            )
        if variant_focus.strip():
            system += (
                "\nVARIANT_FOCUS: "
                + variant_focus.strip()
                + "。这是质量探索，不得改变已给定事实、人物选择、合同义务或知识边界。"
            )
        requirements = [
            "写出目标、实际阻碍、人物选择和可见结果",
            "用动作、环境和必要对话呈现，不写提纲或创作解释",
            "不重复已知信息、不越过知识边界、不新增重大设定",
            "结尾形成可传递变化，避免模板化收束",
        ]
        user = "\n\n".join(
            [
                f"STORY_PREMISE\n{story_premise}",
                "SCENE_BRIEF\n"
                + json.dumps(
                    {
                        "index": scene.scene_index,
                        "title": scene.title,
                        "purpose": scene.purpose or scene.goal,
                        "pov": scene.pov_character or contract.pov_character,
                        "location": scene.location or contract.location,
                        "time": scene.time_context or contract.time_context,
                        "characters": scene.participating_characters,
                        "goal": scene.character_goals or scene.goal,
                        "obstacle": scene.obstacle or scene.conflict,
                        "outcome": scene.outcome,
                        "target_length": scene.target_length,
                    },
                    ensure_ascii=False,
                ),
                "PREVIOUS_SCENE_END_STATE\n"
                + json.dumps(
                    previous_scene_end_state.model_dump() if previous_scene_end_state else {},
                    ensure_ascii=False,
                ),
                f"CHARACTER_STATES\n{json.dumps(character_states, ensure_ascii=False, default=str)[:1800]}",
                "SCENE_CANONICAL_CONTEXT\n"
                + (scene_context or "本场景没有额外检索事实。"),
                "SCENE_CONTRACT_OBLIGATIONS\n"
                + json.dumps(
                    [item["requirement"] for item in execution_checklist], ensure_ascii=False
                )
                + "。执行系统消息中的 CONTRACT_EXECUTION_CHECKLIST。"
                "只兑现分配给当前场景的 must_include / must_end_with 义务；"
                "严格避免 must_exclude，且不可把未分配给本场的事件提前写出。"
                "禁止项必须连同近似动作一起避免：不得以未说完的称呼、半句台词、将要发生的动作"
                "或旁白暗示来触发被禁止的事件。"
                "每项 must_include 都必须由正文中可定位的动作、对白或可见结果证明；"
                "must_show_source 必须写出获得信息的来源；must_end_with 必须落在本场最后一段。",
                "PREVIOUS_SCENE_OBLIGATIONS\n"
                + json.dumps(previous_requirements, ensure_ascii=False)
                + "\n这些义务已由前序场景处理，只能承接其后果，不得把同一事件重新演一遍。",
                f"STYLE_REQUIREMENTS\n{style_requirements[:500]}",
                "FORBIDDEN_ACTIONS\n"
                + json.dumps(
                    forbidden_actions + (transition_constraints or []), ensure_ascii=False
                ),
                "OUTPUT_REQUIREMENTS\n"
                + "\n".join(f"{index}. {item}" for index, item in enumerate(requirements, 1))
                + f"\n目标长度约 {scene.target_length or 600} 字。",
            ]
        )
        # Lower variance only for contract-bound scene drafting. This keeps the
        # creative prose call singular while making the precomputed obligation
        # checklist materially more reliable than a later rewrite loop.
        raw = self._chat(system, user, temperature=0.25 if temperature is None else temperature)
        draft = self._scene_draft_or_prose(raw, scene)
        if draft is None:
            # Truly empty or unusable output still deserves bounded structured repair.
            draft = self._repair_scene_draft(raw, scene)
        if not draft.content.strip():
            raise ValueError("Writer returned empty scene content.")
        draft.content = draft.content.strip()
        return draft

    def _scene_draft_or_prose(self, raw: str, scene: Beat) -> SceneDraft | None:
        """Preserve usable prose when a provider misses only the JSON envelope.

        Scene prose is the primary artifact. Re-asking a model to wrap valid
        prose in a large state schema costs a full extra request per scene and
        can introduce new facts. A conservative empty hand-off is safer than
        treating a planned state as a fact from the prose.
        """
        try:
            # Some providers emit valid JSON structure with typographic quotes
            # (``{“content”: “...”}``). Treat it as JSON, not novel prose;
            # otherwise a schema wrapper can leak into the chapter and poison
            # every later contract check.
            data = extract_json(self._normalize_json_quotes(raw))
        except Exception:
            recovered = self._recover_content_field(raw)
            if recovered:
                return SceneDraft(
                    content=recovered,
                    ending_state=self._conservative_scene_end_state(scene),
                )
            return self._fallback_scene_draft(self._strip_fence(raw), scene)
        if not isinstance(data, dict):
            return None
        content = str(data.get("content") or data.get("prose") or "").strip()
        if not content:
            recovered = self._recover_content_field(raw)
            if recovered:
                return SceneDraft(
                    content=recovered,
                    ending_state=self._conservative_scene_end_state(scene),
                )
            return None
        try:
            ending_state = SceneEndState.model_validate(data.get("ending_state") or {})
        except Exception:
            ending_state = self._conservative_scene_end_state(scene)
        return SceneDraft(content=content, ending_state=ending_state)

    @classmethod
    def _recover_content_field(cls, raw: str) -> str:
        """Recover prose when only a trailing structured hand-off is malformed."""
        text = cls._normalize_json_quotes(raw).strip()
        field = re.search(r'"(?:content|prose)"\s*:\s*"', text, re.IGNORECASE)
        if field is None:
            return ""
        tail = text[field.end() :]
        boundary = re.search(
            r'(?<!\\)"\s*,\s*"(?:ending_state|reason|source_content_digest|scene_index)"\s*:',
            tail,
            re.IGNORECASE | re.DOTALL,
        )
        if boundary is not None:
            value = tail[: boundary.start()]
        else:
            closing = re.search(r'(?<!\\)"\s*}\s*$', tail, re.DOTALL)
            value = tail[: closing.start()] if closing is not None else tail
        return value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\").strip()

    @staticmethod
    def _normalize_json_quotes(raw: str) -> str:
        text = raw.strip()
        if not text.startswith("{"):
            return raw
        return text.translate(
            str.maketrans(
                {
                    "“": '"',
                    "”": '"',
                    "‘": "'",
                    "’": "'",
                }
            )
        )

    def _repair_scene_draft(self, raw: str, scene: Beat) -> SceneDraft:
        last_raw = raw
        last_error: Exception = ValueError("Scene response contains no usable prose.")
        for _ in range(self.structured_repair_attempts):
            last_raw = self._repair_structured_output(
                last_raw,
                SceneDraft,
                last_error,
                is_list=False,
            )
            draft = self._scene_draft_or_prose(last_raw, scene)
            if draft is not None:
                return draft
        raise last_error

    @staticmethod
    def _strip_fence(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            return "\n".join(text.splitlines()[1:-1]).strip()
        return text

    def _fallback_scene_draft(self, content: str, scene: Beat) -> SceneDraft | None:
        clean = content.strip()
        if not clean or clean.startswith("{") or clean.startswith("["):
            return None
        return SceneDraft(content=clean, ending_state=self._conservative_scene_end_state(scene))

    @staticmethod
    def _conservative_scene_end_state(scene: Beat) -> SceneEndState:
        return SceneEndState(characters_present=list(scene.participating_characters))

    def reconcile_scene_end_state(
        self,
        *,
        content: str,
        scene: Beat,
        previous_scene_end_state: SceneEndState | None,
    ) -> SceneEndState:
        """Re-extract the hand-off from final prose after any polishing pass.

        The first SceneDraft state describes pre-polish prose.  A polisher may
        change an action, object, or location, so the next scene must consume a
        state grounded in the final text instead of that stale draft metadata.
        """
        system = (
            "You extract a scene hand-off from final novel prose. Return only strict SceneEndState JSON. "
            "Record only facts explicit in the final prose; do not infer events or preserve facts that the "
            "prose removed. Keep uncertain fields empty."
        )
        user = (
            "scene_end_state_reconcile\n"
            f"scene={json.dumps(scene.model_dump(exclude={'content', 'end_state'}), ensure_ascii=False)}\n"
            "previous_scene_end_state="
            + json.dumps(
                previous_scene_end_state.model_dump() if previous_scene_end_state else {},
                ensure_ascii=False,
            )
            + f"\nfinal_content={content}\n只输出 SceneEndState JSON。"
        )
        return self._chat_model(system, user, SceneEndState)

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
