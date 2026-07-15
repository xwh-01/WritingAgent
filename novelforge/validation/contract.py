"""Validate chapter contracts with deterministic and semantic evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from novelforge.core.utils import extract_json
from novelforge.domain import ChapterContract, ConstraintCheck
from novelforge.llm.base import LLMClient


class ChapterContractValidator:
    """Merge stable rule checks with optional LLM semantic judgments."""

    _STOP_WORDS = {
        "必须",
        "需要",
        "应该",
        "本章",
        "不能",
        "不要",
        "不得",
        "发生",
        "出现",
        "一个",
        "这个",
        "以及",
        "然后",
        "最后",
        "must",
        "should",
        "chapter",
    }
    _SEVERITIES = {
        "pov_character": "high",
        "location": "high",
        "time_context": "high",
        "must_happen": "high",
        "must_not_happen": "critical",
        "character_goal": "high",
        "knowledge_boundary": "critical",
        "knowledge_acquisition": "high",
        "active_thread": "medium",
        "ending_hook": "high",
        "style_requirement": "medium",
    }
    _SEMANTIC_PRIMARY = {
        "pov_character",
        "location",
        "time_context",
        "character_goal",
        "knowledge_boundary",
        "knowledge_acquisition",
        "active_thread",
        "style_requirement",
    }
    _KNOWLEDGE_VERBS = (
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
    _ACQUISITION_VERBS = (
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

    def __init__(self, llm: LLMClient | None = None, min_confidence: float = 0.7) -> None:
        self.llm = llm
        self.min_confidence = min_confidence

    def validate(self, content: str, contract: ChapterContract | None) -> list[ConstraintCheck]:
        if contract is None:
            return []
        checks = self._rule_checks(content, contract)
        semantic = self._semantic_checks(content, checks) if self.llm and checks else []
        by_key = {
            (str(item.get("constraint_type", "")), str(item.get("requirement", ""))): item
            for item in semantic
        }
        for check in checks:
            result = by_key.get((check.constraint_type, check.requirement))
            if result is None:
                continue
            raw_passed = result.get("passed")
            if not isinstance(raw_passed, bool):
                continue
            semantic_passed = raw_passed
            confidence = self._confidence(result.get("confidence"))
            check.semantic_passed = semantic_passed
            check.confidence = confidence
            check.validation_method = "rule+llm"
            semantic_evidence = str(result.get("evidence") or "").strip()
            semantic_paragraph = str(result.get("paragraph_range") or "").strip()
            check.evidence = str(semantic_evidence or check.evidence)[:300]
            check.paragraph_range = str(semantic_paragraph or check.paragraph_range)[:80]
            explanation = str(result.get("explanation") or "").strip()
            rule_conflict = check.rule_passed is not None and semantic_passed != check.rule_passed
            missing_semantic_evidence = check.constraint_type in self._SEMANTIC_PRIMARY and (
                not semantic_evidence or not semantic_paragraph
            )
            if confidence < self.min_confidence or rule_conflict or missing_semantic_evidence:
                check.passed = False
                check.status = "review_required"
                if confidence < self.min_confidence:
                    reason = "语义置信度不足"
                elif rule_conflict:
                    reason = "规则与语义判断冲突"
                else:
                    reason = "语义判断缺少具体证据或段落位置"
                check.message = f"{reason}，需要人工确认。" + (
                    f" {explanation}" if explanation else ""
                )
            else:
                check.passed = semantic_passed
                check.status = "passed" if semantic_passed else "failed"
                if explanation:
                    check.message = explanation
        return checks

    def hard_constraints_passed(self, checks: list[ConstraintCheck]) -> bool:
        return all(
            check.passed and check.status == "passed"
            for check in checks
            if check.severity in {"high", "critical"}
        )

    def _rule_checks(self, content: str, contract: ChapterContract) -> list[ConstraintCheck]:
        checks: list[ConstraintCheck] = []
        seen: set[tuple[str, str]] = set()

        pov = self._clean(contract.pov_character or "")
        if pov:
            evidence, paragraph = self._candidate_evidence(content, pov)
            self._append_check(
                checks,
                seen,
                "pov_character",
                f"主要叙事视角属于: {pov}",
                None,
                evidence,
                paragraph,
                "需要语义判断主要叙事视角及是否存在大面积视角漂移。",
            )

        location = self._clean(contract.location)
        if location:
            evidence, paragraph = self._candidate_evidence(content, location)
            self._append_check(
                checks,
                seen,
                "location",
                f"主要剧情地点: {location}",
                None,
                evidence,
                paragraph,
                "需要语义判断指定地点是否承载本章主要剧情。",
            )

        time_context = self._clean(contract.time_context)
        if time_context:
            evidence, paragraph = self._candidate_evidence(content, time_context)
            self._append_check(
                checks,
                seen,
                "time_context",
                f"主要剧情时间: {time_context}",
                None,
                evidence,
                paragraph,
                "需要语义判断主要剧情时间以及时间顺序是否符合合同。",
            )

        for requirement in self._unique(contract.must_happen):
            matched, evidence, paragraph = self._matches(content, requirement)
            self._append_check(
                checks,
                seen,
                "must_happen",
                requirement,
                matched,
                evidence,
                paragraph,
                "必需情节已出现。" if matched else "正文中未找到足够证据证明必需情节已完成。",
            )
        for requirement in self._unique(contract.must_not_happen):
            matched, evidence, paragraph = self._matches(content, requirement)
            passed = not matched
            self._append_check(
                checks,
                seen,
                "must_not_happen",
                requirement,
                passed,
                evidence,
                paragraph,
                "未触发禁止项。" if passed else "正文可能触发了禁止情节。",
            )

        for character in sorted(contract.character_goals):
            goal = self._clean(contract.character_goals.get(character, ""))
            clean_character = self._clean(character)
            if not clean_character or not goal:
                continue
            evidence, paragraph = self._goal_evidence(content, clean_character, goal)
            self._append_check(
                checks,
                seen,
                "character_goal",
                f"{clean_character}: {goal}",
                None,
                evidence,
                paragraph,
                "需要语义判断人物是否为目标采取实际行动，而非仅提及目标。",
            )

        for character, boundary_type, information in self._knowledge_requirements(contract):
            constraint_type = (
                "knowledge_acquisition" if boundary_type == "acquisition" else "knowledge_boundary"
            )
            if boundary_type == "forbidden":
                requirement = f"{character} 不应知道: {information}"
                violation, evidence, paragraph = self._knowledge_violation(
                    content, character, information
                )
                rule_passed: bool | None = False if violation else None
                message = (
                    "发现人物可能提前掌握禁止信息。"
                    if violation
                    else "需要语义判断人物是否发生知识越界。"
                )
            elif boundary_type == "acquisition":
                requirement = f"{character} 可以通过剧情获得: {information}"
                evidence, paragraph = self._acquisition_evidence(content, character, information)
                rule_passed = None
                message = "需要语义确认新知识是否存在明确来源或获得过程。"
            else:
                requirement = f"{character} 应已知道: {information}"
                evidence, paragraph = self._candidate_evidence(
                    content, information, required_context=character
                )
                rule_passed = None
                message = "需要语义判断人物行为是否符合其已有知识。"
            self._append_check(
                checks,
                seen,
                constraint_type,
                requirement,
                rule_passed,
                evidence,
                paragraph,
                message,
            )

        for thread in self._unique(contract.active_threads):
            evidence, paragraph = self._candidate_evidence(content, thread)
            self._append_check(
                checks,
                seen,
                "active_thread",
                thread,
                None,
                evidence,
                paragraph,
                "需要语义判断故事线是否得到推进、保持或有意识地延迟。",
            )

        ending_hook = self._clean(contract.ending_hook)
        if ending_hook:
            paragraphs = self._paragraphs(content)
            ending = "\n\n".join(paragraphs[max(0, int(len(paragraphs) * 0.7)) :])
            matched, evidence, local_range = self._matches(ending, ending_hook)
            if local_range and paragraphs:
                local_number = int(re.search(r"\d+", local_range).group())
                offset = max(0, int(len(paragraphs) * 0.7))
                local_range = f"段落{offset + local_number}"
            self._append_check(
                checks,
                seen,
                "ending_hook",
                ending_hook,
                matched,
                evidence,
                local_range,
                "结尾钩子已落实。" if matched else "结尾部分未找到指定钩子。",
            )

        for style in self._unique(contract.style_requirements):
            evidence, paragraph = self._style_evidence(content, style)
            self._append_check(
                checks,
                seen,
                "style_requirement",
                style,
                None,
                evidence,
                paragraph,
                "需要语义判断正文是否明显违反文风要求，并提供具体证据。",
            )
        return checks

    def _append_check(
        self,
        checks: list[ConstraintCheck],
        seen: set[tuple[str, str]],
        constraint_type: str,
        requirement: str,
        rule_passed: bool | None,
        evidence: str,
        paragraph_range: str,
        message: str,
    ) -> None:
        clean_requirement = self._clean(requirement)
        key = (constraint_type, clean_requirement)
        if not clean_requirement or key in seen:
            return
        seen.add(key)
        checks.append(
            self._new_check(
                constraint_type,
                clean_requirement,
                rule_passed,
                evidence,
                paragraph_range,
                message,
            )
        )

    def _new_check(
        self,
        constraint_type: str,
        requirement: str,
        rule_passed: bool | None,
        evidence: str,
        paragraph_range: str,
        message: str,
    ) -> ConstraintCheck:
        conclusive = rule_passed is not None
        passed = bool(rule_passed) if conclusive else False
        return ConstraintCheck(
            constraint_type=constraint_type,
            requirement=requirement,
            passed=passed,
            severity=self._SEVERITIES[constraint_type],
            status=("passed" if passed else "failed") if conclusive else "review_required",
            rule_passed=rule_passed,
            evidence=evidence,
            paragraph_range=paragraph_range,
            confidence=1.0 if conclusive else 0.0,
            message=message,
        )

    def _knowledge_requirements(
        self,
        contract: ChapterContract,
    ) -> list[tuple[str, str, str]]:
        requirements: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        priority = {"known": 0, "forbidden": 1, "acquisition": 2}
        for raw_character in sorted(contract.knowledge_boundaries):
            character = self._clean(raw_character)
            boundaries = contract.knowledge_boundaries.get(raw_character) or {}
            if not character or not isinstance(boundaries, dict):
                continue
            ordered = sorted(
                boundaries.items(),
                key=lambda item: (priority[self._knowledge_kind(str(item[0]))], str(item[0])),
            )
            for raw_kind, values in ordered:
                kind = self._knowledge_kind(str(raw_kind))
                for information in self._unique(values or []):
                    key = (character, kind, information)
                    if key not in seen:
                        seen.add(key)
                        requirements.append(key)
        return requirements

    def _knowledge_kind(self, key: str) -> str:
        normalized = re.sub(r"[_\W]+", "", key, flags=re.UNICODE).lower()
        if any(
            token in normalized
            for token in (
                "canlearn",
                "maylearn",
                "canknow",
                "mayknow",
                "acquire",
                "acquisition",
                "learn",
                "gain",
                "可以知道",
                "可以获得",
                "本章获得",
                "可获知",
                "获得",
            )
        ):
            return "acquisition"
        if any(
            token in normalized
            for token in (
                "mustnotknow",
                "cannotknow",
                "forbidden",
                "unknown",
                "doesnotknow",
                "secret",
                "不应知道",
                "不能知道",
                "不可知道",
                "未知",
                "禁止",
            )
        ):
            return "forbidden"
        return "known"

    def _candidate_evidence(
        self,
        content: str,
        requirement: str,
        required_context: str = "",
    ) -> tuple[str, str]:
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            matched, _, _ = self._matches(paragraph, requirement)
            if matched and (
                not required_context
                or self._normalize(required_context) in self._normalize(paragraph)
            ):
                return paragraph[:300], f"段落{index}"
        return "", ""

    def _goal_evidence(self, content: str, character: str, goal: str) -> tuple[str, str]:
        action_verbs = (
            "走",
            "去",
            "找",
            "追",
            "查",
            "问",
            "拿",
            "救",
            "阻止",
            "保护",
            "尝试",
            "决定",
            "拒绝",
            "行动",
        )
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            normalized = self._normalize(paragraph)
            goal_matched, _, _ = self._matches(paragraph, goal)
            if (
                self._normalize(character) in normalized
                and goal_matched
                and any(verb in paragraph for verb in action_verbs)
            ):
                return paragraph[:300], f"段落{index}"
        return self._candidate_evidence(content, goal, required_context=character)

    def _knowledge_violation(
        self,
        content: str,
        character: str,
        information: str,
    ) -> tuple[bool, str, str]:
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            normalized = self._normalize(paragraph)
            information_matched, _, _ = self._matches(paragraph, information)
            if (
                self._normalize(character) in normalized
                and information_matched
                and any(verb in paragraph for verb in self._KNOWLEDGE_VERBS)
            ):
                return True, paragraph[:300], f"段落{index}"
        return False, "", ""

    def _acquisition_evidence(
        self, content: str, character: str, information: str
    ) -> tuple[str, str]:
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            normalized = self._normalize(paragraph)
            information_matched, _, _ = self._matches(paragraph, information)
            if (
                self._normalize(character) in normalized
                and information_matched
                and any(verb in paragraph for verb in self._ACQUISITION_VERBS)
            ):
                return paragraph[:300], f"段落{index}"
        return "", ""

    def _style_evidence(self, content: str, requirement: str) -> tuple[str, str]:
        violation_markers: tuple[str, ...] = ()
        if any(token in requirement for token in ("克制", "减少解释", "少解释")):
            violation_markers = ("显然", "事实上", "这意味着", "他当然知道", "毫无疑问")
        elif "第一人称" in requirement:
            violation_markers = ("他心想", "她心想")
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            if any(marker in paragraph for marker in violation_markers):
                return paragraph[:300], f"段落{index}"
        return "", ""

    def _unique(self, values: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = self._clean(str(value))
            if clean and clean not in seen:
                seen.add(clean)
                unique.append(clean)
        return unique

    def _clean(self, value: str) -> str:
        return value.strip()

    def _semantic_checks(self, content: str, checks: list[ConstraintCheck]) -> list[dict[str, Any]]:
        requirements = [
            {
                "constraint_type": check.constraint_type,
                "requirement": check.requirement,
                "severity": check.severity,
                "rule_passed": check.rule_passed,
                "rule_evidence": check.evidence,
                "rule_paragraph_range": check.paragraph_range,
            }
            for check in checks
        ]
        numbered = "\n".join(
            f"[段落{index}] {paragraph}"
            for index, paragraph in enumerate(self._paragraphs(content), 1)
        )
        prompt = (
            "chapter_contract_semantic_validation\n"
            "逐项判断正文是否满足合同。POV 要判断主导视角而非人称形式；location 判断主要剧情地点；"
            "time_context 允许合理回忆但主要剧情时间不得冲突；character_goal 必须有实际尝试，失败也可通过；"
            "knowledge_boundary 要区分旁白与人物知识，人物确定知道禁止信息才失败；"
            "knowledge_acquisition 必须有信息来源或获得过程；active_thread 需推进、保持或有意识延迟；"
            "style_requirement 必须引用具体违规或符合证据。must_not_happen 的 passed=true 表示禁项没有发生；"
            "ending_hook 只检查结尾30%的段落。规则结果只是证据，不得因语义主导字段规则未匹配而直接失败。"
            "严格输出 JSON 数组，每项必须包含 "
            "constraint_type, requirement, passed, confidence(0-1), evidence, paragraph_range, explanation。\n"
            f"合同项: {json.dumps(requirements, ensure_ascii=False)}\n"
            f"带编号正文:\n{numbered[:16000]}"
        )
        try:
            raw = self.llm.chat_completion([{"role": "user", "content": prompt}])
            data = extract_json(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _matches(self, content: str, requirement: str) -> tuple[bool, str, str]:
        normalized_requirement = self._normalize(requirement)
        if not normalized_requirement:
            return True, "", ""
        tokens = self._tokens(requirement)
        best: tuple[int, int, str] | None = None
        for index, paragraph in enumerate(self._paragraphs(content), 1):
            normalized_paragraph = self._normalize(paragraph)
            if normalized_requirement in normalized_paragraph:
                return True, paragraph[:300], f"段落{index}"
            hits = sum(1 for token in tokens if self._normalize(token) in normalized_paragraph)
            if best is None or hits > best[0]:
                best = (hits, index, paragraph)
        if not tokens or best is None:
            return False, "", ""
        threshold = max(1, (len(tokens) + 1) // 2)
        matched = best[0] >= threshold
        return matched, best[2][:300] if matched else "", f"段落{best[1]}" if matched else ""

    def _paragraphs(self, content: str) -> list[str]:
        return [
            paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()
        ]

    def _tokens(self, text: str) -> list[str]:
        chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", text)
        tokens: list[str] = []
        for chunk in chunks:
            if chunk.lower() in self._STOP_WORDS:
                continue
            if len(chunk) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                tokens.extend(chunk[index : index + 2] for index in range(0, len(chunk) - 1, 2))
            else:
                tokens.append(chunk)
        return list(dict.fromkeys(tokens))

    def _normalize(self, text: str) -> str:
        return re.sub(r"\W+", "", text, flags=re.UNICODE).lower()

    def _confidence(self, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
