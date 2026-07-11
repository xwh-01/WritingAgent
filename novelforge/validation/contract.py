"""Validate chapter contracts with deterministic and semantic evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from novelforge.core.models import ChapterContract, ConstraintCheck
from novelforge.core.utils import extract_json
from novelforge.llm.base import LLMClient


class ChapterContractValidator:
    """Merge stable rule checks with optional LLM semantic judgments."""

    _STOP_WORDS = {
        "必须", "需要", "应该", "本章", "不能", "不要", "不得", "发生", "出现",
        "一个", "这个", "以及", "然后", "最后", "must", "should", "chapter",
    }

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
            semantic_passed = bool(result.get("passed"))
            confidence = self._confidence(result.get("confidence"))
            check.semantic_passed = semantic_passed
            check.confidence = confidence
            check.validation_method = "rule+llm"
            check.evidence = str(result.get("evidence") or check.evidence)[:300]
            check.paragraph_range = str(result.get("paragraph_range") or check.paragraph_range)[:80]
            explanation = str(result.get("explanation") or "").strip()
            if confidence < self.min_confidence or semantic_passed != check.rule_passed:
                check.passed = False
                check.status = "review_required"
                reason = "语义置信度不足" if confidence < self.min_confidence else "规则与语义判断冲突"
                check.message = f"{reason}，需要人工确认。" + (f" {explanation}" if explanation else "")
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
        for requirement in contract.must_happen:
            matched, evidence, paragraph = self._matches(content, requirement)
            checks.append(self._new_check(
                "must_happen", requirement, matched, evidence, paragraph,
                "必需情节已出现。" if matched else "正文中未找到足够证据证明必需情节已完成。",
            ))
        for requirement in contract.must_not_happen:
            matched, evidence, paragraph = self._matches(content, requirement)
            passed = not matched
            checks.append(self._new_check(
                "must_not_happen", requirement, passed, evidence, paragraph,
                "未触发禁止项。" if passed else "正文可能触发了禁止情节。",
            ))
        if contract.ending_hook:
            paragraphs = self._paragraphs(content)
            ending = "\n\n".join(paragraphs[max(0, int(len(paragraphs) * 0.7)):])
            matched, evidence, local_range = self._matches(ending, contract.ending_hook)
            if local_range and paragraphs:
                local_number = int(re.search(r"\d+", local_range).group())
                offset = max(0, int(len(paragraphs) * 0.7))
                local_range = f"段落{offset + local_number}"
            checks.append(self._new_check(
                "ending_hook", contract.ending_hook, matched, evidence, local_range,
                "结尾钩子已落实。" if matched else "结尾部分未找到指定钩子。",
            ))
        return checks

    def _new_check(
        self,
        constraint_type: str,
        requirement: str,
        passed: bool,
        evidence: str,
        paragraph_range: str,
        message: str,
    ) -> ConstraintCheck:
        return ConstraintCheck(
            constraint_type=constraint_type,
            requirement=requirement,
            passed=passed,
            status="passed" if passed else "failed",
            rule_passed=passed,
            evidence=evidence,
            paragraph_range=paragraph_range,
            confidence=1.0,
            message=message,
        )

    def _semantic_checks(self, content: str, checks: list[ConstraintCheck]) -> list[dict[str, Any]]:
        requirements = [
            {"constraint_type": check.constraint_type, "requirement": check.requirement}
            for check in checks
        ]
        numbered = "\n".join(
            f"[段落{index}] {paragraph}" for index, paragraph in enumerate(self._paragraphs(content), 1)
        )
        prompt = (
            "chapter_contract_semantic_validation\n"
            "逐项判断正文是否满足合同。must_not_happen 的 passed=true 表示禁项没有发生；"
            "ending_hook 只检查结尾30%的段落。严格输出 JSON 数组，每项必须包含 "
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
        return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]

    def _tokens(self, text: str) -> list[str]:
        chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", text)
        tokens: list[str] = []
        for chunk in chunks:
            if chunk.lower() in self._STOP_WORDS:
                continue
            if len(chunk) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                tokens.extend(chunk[index:index + 2] for index in range(0, len(chunk) - 1, 2))
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
