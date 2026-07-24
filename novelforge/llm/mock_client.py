"""Deterministic local LLM used for tests and API-key-free demos."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from novelforge.llm.base import LLMClient


class MockLLMClient(LLMClient):
    """基于规则与关键词的本地 Mock LLM 客户端，无需 API Key 即可用于测试和演示。"""

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """根据提示词中的关键词返回对应的预设 JSON 或文本响应。"""
        prompt = "\n".join(message.get("content", "") for message in messages)
        last_user = messages[-1].get("content", "") if messages else ""
        # Route generation commands by the current user message before inspecting
        # recalled context, which may legitimately contain old marker strings.
        if last_user.startswith("generate_beats"):
            return self._mock_scene_plan()
        if '"marker": "director_plan"' in prompt:
            try:
                payload = json.loads(messages[-1].get("content", "{}"))
            except Exception:
                payload = {}
            objective = str(payload.get("objective") or "")
            lowered = objective.lower()
            chapter = self._extract_chapter(objective, 0)
            tasks = []
            character_names = (payload.get("story_state") or {}).get("characters") or []
            selected_character = next(
                (name for name in character_names if str(name).lower() in lowered), None
            )
            range_match = re.search(r"第?\s*(\d+)\s*(?:到|至|[-~])\s*第?\s*(\d+)\s*章?", objective)
            if (
                any(token in objective for token in ("人设", "角色一致", "角色连续"))
                or "character" in lowered
            ):
                if not selected_character:
                    tasks = [
                        {
                            "id": "task-question",
                            "description": "你想检查哪位角色的人设或状态轨迹？",
                            "selected_tool": "ask_user",
                        }
                    ]
                else:
                    start = int(range_match.group(1)) if range_match else 1
                    end = int(range_match.group(2)) if range_match else max(chapter, 1)
                    tasks = [
                        {
                            "id": "task-character-arc",
                            "description": f"审计 {selected_character} 在第{start}到第{end}章的角色连续性",
                            "selected_tool": "analyze_character_continuity",
                            "tool_args": {
                                "character": selected_character,
                                "start_chapter": start,
                                "end_chapter": max(start, end),
                            },
                            "success_criteria": [
                                "给出跨章节角色轨迹和带证据的问题",
                                "定位需要修订的章节",
                            ],
                        }
                    ]
            elif any(token in lowered for token in ("改", "修", "revise")):
                if chapter <= 0:
                    tasks = [
                        {
                            "id": "task-question",
                            "description": "你想修改第几章？",
                            "selected_tool": "ask_user",
                        }
                    ]
                else:
                    tasks = [
                        {
                            "id": "task-inspect",
                            "description": f"读取第{chapter}章当前正文",
                            "selected_tool": "inspect_chapter",
                            "tool_args": {"chapter_index": chapter, "include_content": True},
                            "success_criteria": ["取得当前有效正文和版本"],
                        },
                        {
                            "id": "task-revise",
                            "description": f"生成第{chapter}章候选修订稿",
                            "selected_tool": "revise_chapter",
                            "tool_args": {
                                "chapter_index": chapter,
                                "revision_instruction": objective,
                            },
                            "dependencies": ["task-inspect"],
                            "success_criteria": ["候选稿满足用户要求", "正式正文尚未覆盖"],
                        },
                    ]
            elif "伏笔" in objective or "foreshadow" in lowered:
                tasks = [
                    {
                        "id": "task-foreshadow",
                        "description": "检查未回收伏笔",
                        "selected_tool": "list_foreshadowings",
                        "tool_args": {"status": "pending"},
                        "success_criteria": ["返回未回收伏笔"],
                    }
                ]
            elif any(
                token in lowered for token in ("检查", "审查", "review", "continuity", "连续")
            ):
                if chapter <= 0:
                    tasks = [
                        {
                            "id": "task-question",
                            "description": "你想检查第几章？",
                            "selected_tool": "ask_user",
                        }
                    ]
                else:
                    tasks = [
                        {
                            "id": "task-review",
                            "description": f"审查第{chapter}章",
                            "selected_tool": "review_chapter",
                            "tool_args": {"chapter_index": chapter},
                            "success_criteria": ["给出结构化问题和建议"],
                        }
                    ]
                    if "continuity" in lowered or "连续" in objective:
                        tasks.append(
                            {
                                "id": "task-continuity",
                                "description": f"检查第{chapter}章连续性",
                                "selected_tool": "audit_continuity",
                                "tool_args": {"chapter_index": chapter},
                                "dependencies": ["task-review"],
                                "success_criteria": ["给出连续性风险和证据"],
                            }
                        )
            elif any(token in lowered for token in ("继续", "下一章", "write")):
                current = int((payload.get("story_state") or {}).get("current_chapter") or 0)
                target = max(current + 1, 1)
                tasks = [
                    {
                        "id": "task-outline",
                        "description": f"确保大纲覆盖第{target}章",
                        "selected_tool": "create_outline",
                        "tool_args": {"num_chapters": target},
                        "success_criteria": [f"存在第{target}章大纲"],
                    },
                    {
                        "id": "task-write",
                        "description": f"完成第{target}章写作和质量门",
                        "selected_tool": "auto_write_chapter",
                        "tool_args": {"chapter_index": target},
                        "dependencies": ["task-outline"],
                        "success_criteria": ["章节正文已生成", "质量门执行完成"],
                    },
                ]
            else:
                tasks = [
                    {
                        "id": "task-status",
                        "description": "读取项目状态",
                        "selected_tool": "show_status",
                        "success_criteria": ["返回当前项目状态"],
                    }
                ]
            return json.dumps(
                {
                    "objective": objective,
                    "success_criteria": ["完成用户明确目标", "保留故事事实与连续性"],
                    "tasks": tasks,
                    "status": "planned",
                    "assumptions": [],
                },
                ensure_ascii=False,
            )
        if '"marker": "director_task_evaluation"' in prompt:
            try:
                payload = json.loads(messages[-1].get("content", "{}"))
            except Exception:
                payload = {}
            task = payload.get("task") or {}
            result = payload.get("tool_result") or {}
            criteria = task.get("success_criteria") or ["工具产生有效结果"]
            observation = str(result.get("observation") or result.get("output_summary") or "")
            return json.dumps(
                {
                    "passed": bool(observation),
                    "criterion_results": [
                        {
                            "criterion": criterion,
                            "passed": bool(observation),
                            "evidence": observation[:300],
                        }
                        for criterion in criteria
                    ],
                    "recoverable": True,
                    "recommended_action": (
                        "await_approval" if result.get("requires_approval") else "complete"
                    ),
                    "feedback": "" if observation else "工具没有返回可验收的观察结果。",
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
        if "knowledge_extract" in prompt:
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
                            "metadata": {"source": "mock_knowledge_extract"},
                        }
                    ],
                    "relationships": [],
                    "continuity_constraints": [
                        "后续章节需要保持主角目标、关键线索和世界规则的连续性。"
                    ],
                },
                ensure_ascii=False,
            )
        if "chapter_contract_semantic_validation" in prompt:
            requirements_match = re.search(
                r"合同项:\s*(\[.*?\])\s*\n带编号正文:", prompt, re.DOTALL
            )
            requirements = json.loads(requirements_match.group(1)) if requirements_match else []
            body = prompt.split("带编号正文:", 1)[-1]
            paragraphs = re.findall(r"\[段落(\d+)\]\s*(.*?)(?=\n\[段落\d+\]|$)", body, re.DOTALL)

            def important_tokens(text: str) -> list[str]:
                chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", text)
                tokens: list[str] = []
                for chunk in chunks:
                    if len(chunk) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                        tokens.extend(
                            chunk[index : index + 2] for index in range(0, len(chunk) - 1, 2)
                        )
                    else:
                        tokens.append(chunk)
                return list(dict.fromkeys(tokens))

            def best_match(text: str, candidates=paragraphs):
                tokens = important_tokens(text)
                scored = [
                    (sum(1 for token in tokens if token in paragraph), number, paragraph.strip())
                    for number, paragraph in candidates
                ]
                best = max(scored, default=(0, "", ""), key=lambda row: row[0])
                candidate_text = "\n".join(paragraph for _, paragraph in candidates)
                present = text in candidate_text or (
                    bool(tokens) and best[0] >= max(1, (len(tokens) + 1) // 2)
                )
                return present, best

            results = []
            for item in requirements:
                requirement = str(item.get("requirement", ""))
                constraint_type = str(item.get("constraint_type", ""))
                target = requirement.split(":", 1)[-1].strip()
                present, best = best_match(target)
                passed = present

                if constraint_type == "must_not_happen":
                    passed = not present
                elif constraint_type == "ending_hook":
                    start = max(0, int(len(paragraphs) * 0.7))
                    present, best = best_match(target, paragraphs[start:])
                    passed = present
                elif constraint_type == "pov_character":
                    character = target
                    interior_names = re.findall(r"([\u4e00-\u9fff]{2,4})(?:心里|心想|暗自)", body)
                    drifted = any(
                        name != character and not name.endswith(character)
                        for name in interior_names
                    )
                    passed = (
                        (character in body or "我" in body)
                        and "POV_VIOLATION" not in body
                        and not drifted
                    )
                    present, best = best_match(character)
                elif constraint_type in {"location", "time_context"}:
                    passed = present
                elif constraint_type == "character_goal":
                    character, goal = (requirement.split(":", 1) + [""])[:2]
                    present, best = best_match(goal.strip())
                    action_verbs = (
                        "尝试",
                        "决定",
                        "开始",
                        "动身",
                        "搜查",
                        "追赶",
                        "调查",
                        "阻止",
                        "保护",
                        "行动",
                        "失败",
                    )
                    passed = (
                        character.strip() in body
                        and present
                        and any(verb in best[2] for verb in action_verbs)
                    )
                elif constraint_type == "knowledge_boundary":
                    character = requirement.split(" ", 1)[0].strip()
                    information = target
                    present, best = best_match(information)
                    knowledge_verbs = (
                        "知道",
                        "得知",
                        "明白",
                        "意识到",
                        "认出",
                        "想起",
                        "想到",
                        "说出",
                        "断定",
                        "确认",
                    )
                    violation = (
                        character in best[2]
                        and present
                        and any(verb in best[2] for verb in knowledge_verbs)
                    )
                    if "不应知道" in requirement:
                        passed = not violation
                    else:
                        contradicted = (
                            character in best[2]
                            and present
                            and any(
                                marker in best[2]
                                for marker in ("不知道", "不记得", "遗忘", "毫不知情")
                            )
                        )
                        passed = not contradicted
                elif constraint_type == "knowledge_acquisition":
                    character = requirement.split(" ", 1)[0].strip()
                    information = target
                    present, best = best_match(information)
                    acquisition_verbs = (
                        "发现",
                        "看到",
                        "听到",
                        "听见",
                        "读到",
                        "收到",
                        "调查",
                        "推断",
                        "告诉",
                        "线索",
                        "证据",
                    )
                    passed = (
                        character in best[2]
                        and present
                        and any(verb in best[2] for verb in acquisition_verbs)
                    )
                elif constraint_type == "active_thread":
                    progress_verbs = (
                        "推进",
                        "追查",
                        "调查",
                        "发现",
                        "阻止",
                        "决定",
                        "延迟",
                        "等待",
                        "保护",
                        "解决",
                    )
                    passed = present and any(verb in best[2] for verb in progress_verbs)
                elif constraint_type == "style_requirement":
                    violation_markers = ("STYLE_VIOLATION", "！！！！", "显然", "毫无疑问")
                    violating = next(
                        (
                            (number, text.strip())
                            for number, text in paragraphs
                            if any(marker in text for marker in violation_markers)
                        ),
                        None,
                    )
                    passed = violating is None
                    if violating is not None:
                        best = (1, violating[0], violating[1])
                        present = True
                    elif paragraphs:
                        best = (1, paragraphs[0][0], paragraphs[0][1].strip())
                        present = True
                results.append(
                    {
                        "constraint_type": constraint_type,
                        "requirement": requirement,
                        "passed": passed,
                        "confidence": 0.9,
                        "evidence": best[2][:160] if best[2] else "",
                        "paragraph_range": f"段落{best[1]}" if best[1] else "",
                        "explanation": "Mock 语义验收根据合同类型和正文证据作出确定性判断。",
                    }
                )
            return json.dumps(results, ensure_ascii=False)
        if "unified_generation_review" in prompt:
            obligations_match = re.search(
                r"shared_contract_obligations=(.*?)\nshared_contract_evidence=",
                prompt,
                re.DOTALL,
            )
            try:
                obligations = ast.literal_eval(obligations_match.group(1)) if obligations_match else []
            except Exception:
                obligations = []
            content_match = re.search(r"\ncontent=(.*?)\nschema=", prompt, re.DOTALL)
            evidence = content_match.group(1).strip()[:160] if content_match else "Mock review evidence"
            return json.dumps(
                {
                    "scores": {
                        "logic_consistency": 8.0,
                        "character_fidelity": 8.0,
                        "foreshadowing_handling": 8.0,
                        "pacing": 8.0,
                        "style_uniformity": 8.0,
                    },
                    "quality_issues": [],
                    "quality_comment": "Mock unified review passed.",
                    "continuity_passed": True,
                    "continuity_risk_score": 1.0,
                    "continuity_issues": [],
                    "continuity_summary": "Mock unified continuity passed.",
                    "character_risks": [],
                    "contract_evidence": [
                        {
                            "obligation_id": item.get("id", ""),
                            "passed": True,
                            "confidence": 0.9,
                            "evidence": evidence,
                            "paragraph_range": "段落1",
                        }
                        for item in obligations
                        if item.get("id")
                    ],
                },
                ensure_ascii=False,
            )
        if "scene_candidate_selection" in prompt:
            match = re.search(r"candidates=(.*?)\nReturn candidate_ids", prompt, re.DOTALL)
            try:
                candidates = json.loads(match.group(1)) if match else {}
            except Exception:
                candidates = {}
            # The composer submits the source candidate first and expressive
            # alternatives afterwards. Prefer an alternative without tying the
            # deterministic mock to localized prose markers.
            selected = next(reversed(candidates), "")
            return json.dumps(
                {
                    "selected_id": selected,
                    "reason": "动作、感官细节和结尾压力更具体。",
                    "scores": {key: (8.8 if key == selected else 7.8) for key in candidates},
                },
                ensure_ascii=False,
            )
        if "continuity_patch_audit" in prompt:
            return json.dumps(
                {
                    "chapter_index": 1,
                    "risk_score": 1.0,
                    "passed": True,
                    "issues": [],
                    "summary": "Mock local patch continuity passed.",
                },
                ensure_ascii=False,
            )
        if "quality_scorecard_review" in prompt:
            improved = "【修订稿】" in prompt or "revise_chapter_quality" in prompt
            # ── content-sensitive scoring ──
            # Extract chapter content from the prompt (between "章节内容:" and "故事全局记忆:")
            content_match = re.search(r"章节内容:\s*(.*?)(?:故事全局记忆|$)", prompt, re.DOTALL)
            content = content_match.group(1).strip() if content_match else ""
            content_len = len(content)

            # Quality signal detection
            dialogue_count = sum(content.count(q) for q in ('"', '"', "「", "」", "：", ":“"))
            dialogue_variety = min(3.0, dialogue_count / max(content_len, 1) * 300)

            conflict_keywords = (
                "冲突",
                "选择",
                "代价",
                "危险",
                "失败",
                "背叛",
                "秘密",
                "真相",
                "对抗",
                "挣扎",
            )
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

            def _r(scale: float) -> float:
                return round(_random.uniform(-scale, scale), 2)

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
                issues.append(
                    {
                        "dimension": "逻辑",
                        "severity": "medium",
                        "description": "核心冲突体现不够充分，建议增强对抗或选择的戏剧张力。",
                        "paragraph_range": "",
                        "evidence": "",
                    }
                )
            if dialogue_variety < 1.0:
                issues.append(
                    {
                        "dimension": "节奏",
                        "severity": "medium",
                        "description": "对话占比偏低或对话形式单一，建议增加人物互动和潜台词。",
                        "paragraph_range": "",
                        "evidence": "",
                    }
                )
            if structure_bonus < 0.5:
                issues.append(
                    {
                        "dimension": "节奏",
                        "severity": "low",
                        "description": "场景分段偏少，可能缺乏节奏变化。",
                        "paragraph_range": "",
                        "evidence": "",
                    }
                )
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
        if "scene_end_state_reconcile" in prompt:
            scene_match = re.search(r'"scene_index"\s*:\s*(\d+)', prompt)
            scene_index = int(scene_match.group(1)) if scene_match else 1
            return json.dumps(
                {
                    "characters_present": ["主角"],
                    "character_state_changes": {"主角": "已采取行动并承担后果"},
                    "relationship_changes": [],
                    "location_changes": {"主角": f"场景{scene_index}终点"},
                    "time_changes": "",
                    "knowledge_gained": {"主角": [f"线索{scene_index}"]},
                    "items_gained": {},
                    "items_lost": {},
                    "injuries_or_conditions": {},
                    "decisions": {"主角": "继续追查"},
                    "promises": [],
                    "questions_created": ["线索指向何处"],
                    "questions_resolved": [],
                    "ending_state": {"scene_completed": scene_index, "grounded_in": "polished"},
                },
                ensure_ascii=False,
            )
        if "scene_contract_repair_patch" in prompt:
            scene_match = re.search(r"scene=(.*?)\nfailed_evidence=", prompt, re.DOTALL)
            try:
                scene = json.loads(scene_match.group(1)) if scene_match else {}
            except Exception:
                scene = {}
            content = str(scene.get("content") or "").strip()
            return json.dumps(
                {
                    "scene_index": scene.get("scene_index"),
                    "content": "【合同修补】" + content,
                    "ending_state": {"characters_present": scene.get("participating_characters") or []},
                    "reason": "补足已引用的合同义务。",
                },
                ensure_ascii=False,
            )
        if "scene_contract_repair" in prompt:
            obligations_match = re.search(
                r"scene_obligations=(.*?)\nfailed_evidence=", prompt, re.DOTALL
            )
            source_match = re.search(r"scene_content=(.*?)\nOutput only", prompt, re.DOTALL)
            obligations = (
                json.loads(obligations_match.group(1)) if obligations_match else []
            )
            source = source_match.group(1).strip() if source_match else ""
            required = [
                str(item.get("requirement", "")).strip()
                for item in obligations
                if item.get("mode") in {"must_include", "must_end_with", "must_show_source"}
            ]
            additions = "\n".join(item for item in required if item)
            return "\n\n".join(part for part in (source, additions) if part)
        if "scene_revision_proposal" in prompt:
            match = re.search(r"scenes=(.*?)\nOutput only", prompt, re.DOTALL)
            try:
                scenes = json.loads(match.group(1)) if match else []
            except Exception:
                scenes = []
            return json.dumps(
                [
                    {
                        "scene_index": item.get("scene_index"),
                        "content": "【修订场景】" + str(item.get("content") or ""),
                        "reason": "加强冲突与人物选择。",
                    }
                    for item in scenes
                    if item.get("scene_index") and str(item.get("content") or "").strip()
                ],
                ensure_ascii=False,
            )
        if (
            ("CURRENT_SCENE" in prompt or "SCENE_BRIEF" in prompt)
            and "PREVIOUS_SCENE_END_STATE" in prompt
        ):
            scene_match = re.search(r'"(?:scene_index|index)"\s*:\s*(\d+)', prompt)
            scene_index = int(scene_match.group(1)) if scene_match else 1
            variant_suffix = (
                "【表现探索】雨水沿着门锁滑落，他把决定压进一次更清晰的呼吸里。"
                if "VARIANT_FOCUS" in prompt
                else ""
            )
            return json.dumps(
                {
                    "content": (
                        f"场景{scene_index}中，主角沿着潮湿的走廊逼近目标。阻碍突然出现，"
                        "他没有退后，而是主动改变路线并承担暴露行踪的代价。门锁在身后合拢，"
                        "新的线索已经落入手中，局面也因此发生了具体变化。"
                        + variant_suffix
                    ),
                    "ending_state": {
                        "characters_present": ["主角"],
                        "character_state_changes": {"主角": "已采取行动并承担后果"},
                        "relationship_changes": [],
                        "location_changes": {"主角": f"场景{scene_index}终点"},
                        "time_changes": "",
                        "knowledge_gained": {"主角": [f"线索{scene_index}"]},
                        "items_gained": {},
                        "items_lost": {},
                        "injuries_or_conditions": {},
                        "decisions": {"主角": "继续追查"},
                        "promises": [],
                        "questions_created": ["线索指向何处"],
                        "questions_resolved": [],
                        "ending_state": {"scene_completed": scene_index},
                    },
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
            return self._mock_scene_plan()
        return (
            "夜幕降临时，雾气从低洼处漫上来。\n\n"
            "主角握紧手中的线索，意识到真正的对手并不在明处。每一步推进都像踩在薄冰上，"
            "但退后意味着让在乎的人陷入更大的危险。\n\n"
            "当远处的钟声响起，他终于做出选择：去见那个最不该相信的人。"
        )

    @staticmethod
    def _mock_scene_plan() -> str:
        return json.dumps(
            [
                {
                    "scene_index": 1,
                    "title": "进入压力场",
                    "purpose": "建立本章目标并迫使主角行动",
                    "pov_character": "主角",
                    "location": "入口",
                    "time_context": "当晚",
                    "participating_characters": ["主角"],
                    "character_goals": {"主角": "取得关键线索"},
                    "conflict": "目标受到守卫阻拦",
                    "obstacle": "入口被封锁",
                    "must_happen": ["主角主动选择潜入"],
                    "must_not_happen": [],
                    "information_revealed": ["线索藏在内部"],
                    "start_state": {},
                    "end_state": {"location_changes": {"主角": "内部"}},
                    "transition_to_next": "主角带着线索接触关键人物",
                    "target_length": 900,
                    "description": "主角进入新环境，旧问题以新的形式出现。",
                    "goal": "取得推进主线所需的关键线索。",
                    "outcome": "线索到手，但暴露了更大的风险。",
                    "content": "",
                    "status": "planned",
                },
                {
                    "scene_index": 2,
                    "title": "代价与钩子",
                    "purpose": "让胜利产生代价并完成结尾钩子",
                    "pov_character": "主角",
                    "location": "会面处",
                    "time_context": "稍后",
                    "participating_characters": ["主角", "关键人物"],
                    "character_goals": {"主角": "验证线索", "关键人物": "守住秘密"},
                    "conflict": "双方目标互不相容",
                    "obstacle": "关键人物拒绝合作",
                    "must_happen": ["胜利带来代价"],
                    "must_not_happen": [],
                    "information_revealed": ["危险仍在扩大"],
                    "start_state": {},
                    "end_state": {"hook": "新的危险浮现"},
                    "transition_to_next": "",
                    "target_length": 900,
                    "description": "主角与关键人物交锋，关系发生微妙变化。",
                    "goal": "逼近真相并守住底线。",
                    "outcome": "胜利带来代价，章节以悬念收束。",
                    "content": "",
                    "status": "planned",
                },
            ],
            ensure_ascii=False,
        )

    def _extract_int(self, text: str, default: int) -> int:
        """从文本中提取章节数等整数，未匹配时返回默认值。"""
        match = re.search(r"(\d+)\s*(?:章|chapters|ChapterOutline)", text, re.IGNORECASE)
        return int(match.group(1)) if match else default

    def _extract_chapter(self, text: str, default: int) -> int:
        """从文本中提取章节序号，未匹配时返回默认值。"""
        match = re.search(
            r"(?:第\s*)?(\d+)\s*(?:章|chapter|ch)|(?:chapter|ch)\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        return int(match.group(1) or match.group(2)) if match else default

    def _last_user_text(self, messages: list[dict[str, str]]) -> str:
        """获取对话记录中最后一条 user 角色的消息内容。"""
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return messages[-1].get("content", "") if messages else ""
