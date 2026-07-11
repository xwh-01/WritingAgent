"""Deterministic local LLM used for tests and API-key-free demos."""

from __future__ import annotations

import json
import re
from typing import Any

from novelforge.llm.base import LLMClient


class MockLLMClient(LLMClient):
    """基于规则与关键词的本地 Mock LLM 客户端，无需 API Key 即可用于测试和演示。"""

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """根据提示词中的关键词返回对应的预设 JSON 或文本响应。"""
        prompt = "\n".join(message.get("content", "") for message in messages)
        if "director_decision" in prompt:
            step = self._extract_step(prompt)
            if "伏笔" in prompt:
                intent, tool, args, reason, cont = (
                    "inspect_foreshadowing",
                    "list_foreshadowings",
                    {"status": "pending"},
                    "The user asked to inspect unresolved foreshadowings.",
                    False,
                )
            elif "检查" in prompt or "审查" in prompt:
                intent, tool, args, reason, cont = (
                    "review_chapter",
                    "review_chapter",
                    {"chapter_index": self._extract_chapter(prompt, 1)},
                    "The user asked to inspect chapter quality.",
                    False,
                )
            elif "改" in prompt or "修" in prompt:
                intent, tool, args, reason, cont = (
                    "revise_chapter",
                    "revise_chapter",
                    {"chapter_index": self._extract_chapter(prompt, 1)},
                    "The user asked to revise a chapter.",
                    False,
                )
            elif "继续" in prompt or "下一章" in prompt:
                if step <= 1:
                    intent, tool, args, reason, cont = (
                        "prepare_next_chapter",
                        "create_outline",
                        {"num_chapters": 1},
                        "Ensure outline coverage before writing.",
                        True,
                    )
                else:
                    intent, tool, args, reason, cont = (
                        "write_next_chapter",
                        "auto_write_chapter",
                        {"chapter_index": 1},
                        "Write the requested next chapter through the auto-writing loop.",
                        False,
                    )
            else:
                intent, tool, args, reason, cont = (
                    "show_status",
                    "show_status",
                    {},
                    "Show current story status for a broad request.",
                    False,
                )
            return json.dumps(
                {
                    "step": step,
                    "intent": intent,
                    "selected_tool": tool,
                    "reasoning_summary": reason,
                    "tool_args": args,
                    "should_continue": cont,
                    "user_message": "",
                },
                ensure_ascii=False,
            )
        if "supervisor_plan" in prompt:
            return json.dumps(
                {
                    "strategy": "llm_validated_chapter_pipeline",
                    "notes": "Mock Supervisor chose a validated chapter pipeline.",
                    "tasks": [
                        {
                            "agent": "PlannerAgent",
                            "action": "ensure_outline",
                            "reason": "A chapter map is required before scene work.",
                            "chapter_index": None,
                            "input_summary": "Ensure outline coverage.",
                        },
                        {
                            "agent": "PlannerAgent",
                            "action": "generate_beats",
                            "reason": "Scene beats anchor the first chapter.",
                            "chapter_index": 1,
                            "input_summary": "Generate scene beats.",
                        },
                        {
                            "agent": "WriterAgent",
                            "action": "write_chapter",
                            "reason": "Draft the chapter before audits.",
                            "chapter_index": 1,
                            "input_summary": "Write the requested chapter.",
                        },
                        {
                            "agent": "ContinuityAuditorAgent",
                            "action": "audit_chapter_continuity",
                            "reason": "Check continuity after drafting.",
                            "chapter_index": 1,
                            "input_summary": "Audit continuity.",
                        },
                        {
                            "agent": "MemoryEngine",
                            "action": "memory_checkpoint",
                            "reason": "Persist chapter memory.",
                            "chapter_index": 1,
                            "input_summary": "Update memory.",
                        },
                    ],
                },
                ensure_ascii=False,
            )
        if "continuity_audit" in prompt:
            return json.dumps(
                {
                    "chapter_index": 1,
                    "risk_score": 2.0,
                    "passed": True,
                    "issues": [],
                    "checked_constraints": ["mock continuity constraint checked"],
                    "summary": "Mock continuity audit passed.",
                },
                ensure_ascii=False,
            )
        if "memory_extract" in prompt:
            return json.dumps(
                {
                    "characters": [
                        {
                            "id": "protagonist",
                            "name": "主角",
                            "age": "unknown",
                            "appearance": "",
                            "personality": "在压力中成长、善于观察",
                            "motivation": "完成当前目标并保护重要线索",
                            "weakness": "",
                            "relationships": {},
                            "secrets": [],
                            "arc": "",
                        }
                    ],
                    "world_settings": [
                        {
                            "id": "world-core-setting",
                            "category": "world_rule",
                            "content": "关键场景和规则会持续影响人物能力与剧情推进。",
                            "metadata": {"source": "mock_memory_extract"},
                        }
                    ],
                    "relationships": [],
                    "continuity_constraints": ["后续章节需要保持主角目标、关键线索和世界规则的连续性。"],
                },
                ensure_ascii=False,
            )
        if "chapter_contract_semantic_validation" in prompt:
            requirements_match = re.search(r"合同项:\s*(\[.*?\])\s*\n带编号正文:", prompt, re.DOTALL)
            requirements = json.loads(requirements_match.group(1)) if requirements_match else []
            body = prompt.split("带编号正文:", 1)[-1]
            paragraphs = re.findall(r"\[段落(\d+)\]\s*(.*?)(?=\n\[段落\d+\]|$)", body, re.DOTALL)
            results = []
            for item in requirements:
                requirement = str(item.get("requirement", ""))
                chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", requirement)
                tokens = []
                for chunk in chunks:
                    if len(chunk) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                        tokens.extend(chunk[index:index + 2] for index in range(0, len(chunk) - 1, 2))
                    else:
                        tokens.append(chunk)
                scored = [
                    (sum(1 for token in tokens if token in text), number, text.strip())
                    for number, text in paragraphs
                ]
                best = max(scored, default=(0, "", ""), key=lambda row: row[0])
                present = requirement in body or (bool(tokens) and best[0] >= max(1, (len(tokens) + 1) // 2))
                constraint_type = str(item.get("constraint_type", ""))
                passed = not present if constraint_type == "must_not_happen" else present
                results.append({
                    "constraint_type": constraint_type,
                    "requirement": requirement,
                    "passed": passed,
                    "confidence": 0.9,
                    "evidence": best[2][:160] if present else "",
                    "paragraph_range": f"段落{best[1]}" if present and best[1] else "",
                    "explanation": "Mock 语义验收与可复现规则判断一致。",
                })
            return json.dumps(results, ensure_ascii=False)
        if "quality_scorecard_review" in prompt:
            improved = "【修订稿】" in prompt or "revise_chapter_quality" in prompt
            # ── content-sensitive scoring ──
            # Extract chapter content from the prompt (between "章节内容:" and "故事全局记忆:")
            content_match = re.search(r"章节内容:\s*(.*?)(?:故事全局记忆|$)", prompt, re.DOTALL)
            content = content_match.group(1).strip() if content_match else ""
            content_len = len(content)

            # Quality signal detection
            dialogue_count = sum(content.count(q) for q in ("\"", "\"", "「", "」", "：", ":“"))
            dialogue_variety = min(3.0, dialogue_count / max(content_len, 1) * 300)

            conflict_keywords = ("冲突", "选择", "代价", "危险", "失败", "背叛", "秘密", "真相", "对抗", "挣扎")
            conflict_signals = sum(1 for kw in conflict_keywords if kw in content)
            conflict_bonus = min(2.0, conflict_signals * 0.4)

            scene_transitions = content.count("\n\n") + content.count("\n\n")
            structure_bonus = min(1.5, scene_transitions / 5.0)

            quality_bonus = dialogue_variety + conflict_bonus + structure_bonus

            if improved:
                # Revised draft: base starts higher, quality bonuses still apply
                base = round(7.5 + quality_bonus * 0.3, 2)
                base = min(base, 9.2)
            else:
                # Fresh draft: base starts lower, quality bonuses apply
                base = round(5.0 + quality_bonus * 0.5, 2)
                base = min(base, 7.5)

            # Per-dimension jitter for realistic variance
            import random as _random
            _r = lambda scale: round(_random.uniform(-scale, scale), 2)

            scores = {
                "logic_consistency": round(base + _r(0.4), 2),
                "character_fidelity": round(base + 0.2 + _r(0.3), 2),
                "foreshadowing_handling": round(base - 0.1 + _r(0.5), 2),
                "pacing": round(base + _r(0.4), 2),
                "style_uniformity": round(base + 0.1 + _r(0.3), 2),
            }
            # Clamp to 1.0-10.0
            scores = {k: max(1.0, min(10.0, v)) for k, v in scores.items()}

            # Build realistic issues list
            issues = []
            if conflict_signals < 3:
                issues.append({
                    "dimension": "逻辑",
                    "severity": "medium",
                    "description": "核心冲突体现不够充分，建议增强对抗或选择的戏剧张力。",
                    "paragraph_range": "",
                    "evidence": "",
                })
            if dialogue_variety < 1.0:
                issues.append({
                    "dimension": "节奏",
                    "severity": "medium",
                    "description": "对话占比偏低或对话形式单一，建议增加人物互动和潜台词。",
                    "paragraph_range": "",
                    "evidence": "",
                })
            if structure_bonus < 0.5:
                issues.append({
                    "dimension": "节奏",
                    "severity": "low",
                    "description": "场景分段偏少，可能缺乏节奏变化。",
                    "paragraph_range": "",
                    "evidence": "",
                })
            if improved:
                # Revised drafts have fewer issues
                issues = issues[:1] if base < 8.0 else []

            return json.dumps(
                {
                    "scores": scores,
                    "issues": issues,
                    "overall_comment": f"质量评分卡由 Mock LLM 生成（内容长度 {content_len} 字，质量信号 {quality_bonus:.1f}）。",
                },
                ensure_ascii=False,
            )
        if "ReviewReport" in prompt or "审查报告" in prompt:
            return json.dumps(
                {
                    "logic_issues": [],
                    "character_issues": [],
                    "pacing_issues": ["中段可增加一个更明确的转折。"],
                    "suggestions": ["强化章节末尾的悬念钩子。", "让主角的选择带来可见代价。"],
                    "verdict": "needs_revision",
                },
                ensure_ascii=False,
            )
        if "prose_polish" in prompt:
            return (
                "【润色稿】\n"
                "夜色压低了街角的灯光，薄雾贴着地面缓缓流动。\n\n"
                "主角站在岔路口，听见自己的呼吸被四周的寂静放大。那条刚刚到手的线索像一枚发烫的硬币，"
                "压在掌心，也压在选择上。他知道退后一步会更安全，可有些真相一旦露出边角，就再也无法装作没看见。\n\n"
                "远处传来钟声。他向前踏出半步，风掠过耳侧，危险也随之逼近。"
            )
        if "润色" in prompt or "revise_chapter" in prompt:
            return "【修订稿】\n" + self._last_user_text(messages)
        if "generate_outline" in prompt:
            num = self._extract_int(prompt, default=5)
            return json.dumps(
                [
                    {
                        "chapter_index": i,
                        "title": f"第{i}章",
                        "summary": f"主角在第{i}个关键节点面对新的阻力，并发现更深层的真相。",
                        "conflict": "外部压力与内心选择的冲突逐步升级。",
                        "pov_character": "主角",
                    }
                    for i in range(1, num + 1)
                ],
                ensure_ascii=False,
            )
        if "generate_beats" in prompt:
            return json.dumps(
                [
                    {
                        "scene_index": 1,
                        "description": "主角进入新环境，旧问题以新的形式出现。",
                        "goal": "取得推进主线所需的关键线索。",
                        "outcome": "线索到手，但暴露了更大的风险。",
                    },
                    {
                        "scene_index": 2,
                        "description": "主角与关键人物交锋，关系发生微妙变化。",
                        "goal": "逼近真相并守住底线。",
                        "outcome": "胜利带来代价，章节以悬念收束。",
                    },
                ],
                ensure_ascii=False,
            )
        return (
            "夜幕降临时，雾气从低洼处漫上来。\n\n"
            "主角握紧手中的线索，意识到真正的对手并不在明处。每一步推进都像踩在薄冰上，"
            "但退后意味着让在乎的人陷入更大的危险。\n\n"
            "当远处的钟声响起，他终于做出选择：去见那个最不该相信的人。"
        )

    def _extract_int(self, text: str, default: int) -> int:
        """从文本中提取章节数等整数，未匹配时返回默认值。"""
        match = re.search(r"(\d+)\s*(?:章|chapters|ChapterOutline)", text, re.IGNORECASE)
        return int(match.group(1)) if match else default

    def _extract_step(self, text: str) -> int:
        """从 JSON 文本中解析 "step" 字段的数值，默认返回 1。"""
        match = re.search(r'"step"\s*:\s*(\d+)', text)
        return int(match.group(1)) if match else 1

    def _extract_chapter(self, text: str, default: int) -> int:
        """从文本中提取章节序号，未匹配时返回默认值。"""
        match = re.search(r"(?:第)?\s*(\d+)\s*(?:章|chapter|ch)", text, re.IGNORECASE)
        return int(match.group(1)) if match else default

    def _last_user_text(self, messages: list[dict[str, str]]) -> str:
        """获取对话记录中最后一条 user 角色的消息内容。"""
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return messages[-1].get("content", "") if messages else ""
