"""Deterministic local LLM used for tests and API-key-free demos."""

from __future__ import annotations

import json
import re
from typing import Any

from novelforge.llm.base import LLMClient


class MockLLMClient(LLMClient):
    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        prompt = "\n".join(message.get("content", "") for message in messages)
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
                            "id": "hero",
                            "name": "主角",
                            "age": "unknown",
                            "appearance": "",
                            "personality": "敏锐、在压力中成长",
                            "motivation": "完成当前目标并保护关键线索",
                            "weakness": "",
                            "relationships": {},
                            "secrets": [],
                            "arc": "",
                        }
                    ],
                    "world_settings": [
                        {
                            "id": "world-core-training",
                            "category": "training",
                            "content": "训练、比赛和关键线索会持续影响人物能力与剧情推进。",
                            "metadata": {"source": "mock_memory_extract"},
                        }
                    ],
                    "relationships": [],
                    "continuity_constraints": ["后续章节需要保持主角目标、关键线索和训练代价的连续性。"],
                },
                ensure_ascii=False,
            )
        if "quality_scorecard_review" in prompt:
            improved = "【修订稿】" in prompt or "revise_chapter_quality" in prompt
            base = 8.8 if improved else 6.4
            return json.dumps(
                {
                    "scores": {
                        "logic_consistency": base,
                        "character_fidelity": base + 0.2,
                        "foreshadowing_handling": base - 0.1,
                        "pacing": base,
                        "style_uniformity": base + 0.1,
                    },
                    "issues": []
                    if improved
                    else [
                        {
                            "dimension": "节奏",
                            "severity": "medium",
                            "description": "中段转折不够明确，主角选择的代价还不够可见。",
                        }
                    ],
                    "overall_comment": "质量评分卡由 Mock LLM 生成。",
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
                "夜色压低了球场边缘的灯光，草叶上浮着一层细亮的水汽。\n\n"
                "主角站在门线前，听见自己的呼吸被看台的空旷放大。那条刚刚到手的线索像一枚发烫的硬币，"
                "压在掌心，也压在他的选择上。他知道退后一步会更安全，可有些真相一旦露出边角，就再也无法装作没看见。\n\n"
                "哨声响起时，他向前踏出半步。风掠过耳侧，危险也随之逼近。"
            )
        if "润色" in prompt or "revise_chapter" in prompt:
            return "【修订稿】\n" + self._last_user_text(messages)
        if "generate_outline" in prompt:
            num = self._extract_int(prompt, default=5)
            return json.dumps(
                [
                    {
                        "chapter_index": i,
                        "title": f"第{i}章 试炼的回声",
                        "summary": f"主角在第{i}个关键节点面对新的阻力，并发现更深层的真相。",
                        "conflict": "目标与代价之间的冲突逐步升级。",
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
                        "description": "主角进入新场景，旧问题以新的形式出现。",
                        "goal": "取得推进主线所需的线索。",
                        "outcome": "线索到手，但暴露了更危险的对手。",
                    },
                    {
                        "scene_index": 2,
                        "description": "主角与关键人物交锋，关系发生细微改变。",
                        "goal": "逼近真相并守住底线。",
                        "outcome": "胜利带来代价，章节以悬念收束。",
                    },
                ],
                ensure_ascii=False,
            )
        return (
            "夜色压在城墙上，风从残破的旗帜间穿过。\n\n"
            "主角握紧手中的线索，意识到真正的敌人并不在眼前。每一步推进都像踩在薄冰上，"
            "但退后意味着让更多人被黑暗吞没。\n\n"
            "当钟声响起，他终于做出选择：去见那个最不该相信的人。"
        )

    def _extract_int(self, text: str, default: int) -> int:
        match = re.search(r"(\d+)\s*(?:章|chapters|ChapterOutline)", text, re.IGNORECASE)
        return int(match.group(1)) if match else default

    def _last_user_text(self, messages: list[dict[str, str]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return messages[-1].get("content", "") if messages else ""
