"""Compile a chapter contract into scene-level, auditable obligations."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from novelforge.domain import (
    Beat,
    ChapterContract,
    CheckStatus,
    ConstraintCheck,
    ContractConflict,
    ContractEvidence,
    ContractEvidenceLedger,
    ContractExecutionPlan,
    SceneObligation,
    Severity,
)


class ContractObligationCompiler:
    """Assign contract work to scenes before drafting and map checks back afterwards."""

    _NEGATIVE_MARKERS = ("不", "未", "禁止", "不得", "不能", "勿", "not", "never")

    def compile(self, contract: ChapterContract, beats: list[Beat]) -> ContractExecutionPlan:
        ordered = sorted(beats, key=lambda item: item.scene_index)
        conflicts = self._find_conflicts(contract, ordered)
        if not ordered:
            # Imported or legacy candidates may not retain Beat metadata. Keep
            # them reviewable by assigning a synthetic chapter-wide scene;
            # freshly composed chapters always have real scene assignments.
            ordered = [Beat(scene_index=1, title="chapter-wide obligation")]

        obligations: list[SceneObligation] = []
        earliest_scene = ordered[0].scene_index
        for requirement in self._unique(contract.must_happen):
            scene = (
                ordered[-1]
                if self._is_ending_requirement(requirement)
                else self._best_scene(
                    requirement,
                    [item for item in ordered if item.scene_index >= earliest_scene] or ordered,
                )
            )
            obligations.append(
                self._obligation(
                    "must_happen",
                    requirement,
                    scene.scene_index,
                    Severity.HIGH,
                    "must_include",
                )
            )
            earliest_scene = max(earliest_scene, scene.scene_index)
        for requirement in self._unique(contract.must_not_happen):
            for scene in ordered:
                obligations.append(
                    self._obligation(
                        "must_not_happen",
                        requirement,
                        scene.scene_index,
                        Severity.CRITICAL,
                        "must_exclude",
                    )
                )
        for character, kind, requirement in self._knowledge_requirements(contract):
            scene = self._best_scene(requirement, ordered, character)
            obligations.append(
                self._obligation(
                    "knowledge_acquisition" if kind == "acquisition" else "knowledge_boundary",
                    self._knowledge_requirement_label(character, kind, requirement),
                    scene.scene_index,
                    Severity.HIGH if kind == "acquisition" else Severity.CRITICAL,
                    "must_show_source" if kind == "acquisition" else "must_preserve_boundary",
                )
            )
        if contract.ending_hook.strip():
            obligations.append(
                self._obligation(
                    "ending_hook",
                    contract.ending_hook.strip(),
                    ordered[-1].scene_index,
                    Severity.HIGH,
                    "must_end_with",
                )
            )
        return ContractExecutionPlan(
            chapter_index=contract.chapter_index,
            obligations=obligations,
            conflicts=conflicts,
        )

    def conflict_checks(self, plan: ContractExecutionPlan) -> list[ConstraintCheck]:
        return [
            ConstraintCheck(
                constraint_type="contract_conflict",
                requirement=" | ".join(item.requirements) or item.code,
                passed=False,
                severity=item.severity,
                status=CheckStatus.FAILED,
                message=item.message,
                validation_method="obligation_compiler",
            )
            for item in plan.conflicts
        ]

    def build_ledger(
        self,
        plan: ContractExecutionPlan,
        checks: list[ConstraintCheck],
        beats: list[Beat] | None = None,
    ) -> ContractEvidenceLedger:
        by_requirement: dict[tuple[str, str], list[ConstraintCheck]] = defaultdict(list)
        for check in checks:
            by_requirement[(check.constraint_type, self._clean(check.requirement))].append(check)

        entries: list[ContractEvidence] = []
        for obligation in plan.obligations:
            matching = by_requirement.get(
                (obligation.constraint_type, self._clean(obligation.requirement)), []
            )
            check = matching[0] if matching else None
            passed = bool(check and check.passed and check.status == CheckStatus.PASSED)
            evidence_scene = self._evidence_scene(check.evidence if check else "", beats or [])
            if (
                check
                and obligation.constraint_type == "must_not_happen"
                and evidence_scene is not None
            ):
                passed = obligation.scene_index != evidence_scene
            keep_evidence = not (
                obligation.constraint_type == "must_not_happen"
                and evidence_scene is not None
                and passed
            )
            entries.append(
                ContractEvidence(
                    obligation_id=obligation.id,
                    scene_index=obligation.scene_index,
                    constraint_type=obligation.constraint_type,
                    requirement=obligation.requirement,
                    passed=passed,
                    status=check.status if check else CheckStatus.REVIEW_REQUIRED,
                    evidence=(check.evidence if check and keep_evidence else ""),
                    paragraph_range=(check.paragraph_range if check and keep_evidence else ""),
                    failure_category=self._failure_category(obligation, check, passed),
                )
            )
        return ContractEvidenceLedger(chapter_index=plan.chapter_index, plan=plan, entries=entries)

    @staticmethod
    def _evidence_scene(evidence: str, beats: list[Beat]) -> int | None:
        clean = evidence.strip()
        if not clean:
            return None
        for scene in beats:
            scene_content = scene.content.strip()
            if scene_content and (clean in scene_content or scene_content in clean):
                return scene.scene_index
        return None

    def _find_conflicts(
        self,
        contract: ChapterContract,
        beats: list[Beat],
    ) -> list[ContractConflict]:
        conflicts: list[ContractConflict] = []
        for required in self._unique(contract.must_happen):
            for forbidden in self._unique(contract.must_not_happen):
                if self._same_action(required, forbidden):
                    conflicts.append(
                        ContractConflict(
                            code="required_forbidden_overlap",
                            message="The same action is both required and forbidden by the chapter contract.",
                            requirements=[required, forbidden],
                        )
                    )
        if contract.ending_hook.strip():
            for forbidden in self._unique(contract.must_not_happen):
                if self._same_action(contract.ending_hook, forbidden):
                    conflicts.append(
                        ContractConflict(
                            code="ending_hook_forbidden_overlap",
                            message="The ending hook requires an action prohibited by the chapter contract.",
                            requirements=[contract.ending_hook, forbidden],
                        )
                    )
        known: dict[tuple[str, str], set[str]] = defaultdict(set)
        for character, kind, information in self._knowledge_requirements(contract):
            known[(character, self._clean(information))].add(kind)
        for (character, information), kinds in known.items():
            if "known" in kinds and "forbidden" in kinds:
                conflicts.append(
                    ContractConflict(
                        code="knowledge_boundary_overlap",
                        message="A character is simultaneously required to know and forbidden to know the same fact.",
                        requirements=[f"{character}: {information}"],
                    )
                )
        duplicate_ids = [item.scene_index for item in beats if item.scene_index <= 0]
        if duplicate_ids:
            conflicts.append(
                ContractConflict(
                    code="invalid_scene_index",
                    message="Scene obligations require positive scene indexes.",
                    requirements=[str(item) for item in duplicate_ids],
                )
            )
        return conflicts

    def _best_scene(self, requirement: str, beats: list[Beat], character: str = "") -> Beat:
        def score(scene: Beat) -> tuple[int, int]:
            source = " ".join(
                [
                    scene.title,
                    scene.purpose,
                    scene.goal,
                    scene.outcome,
                    scene.conflict,
                    scene.obstacle,
                    " ".join(scene.must_happen),
                    " ".join(scene.information_revealed),
                    " ".join(scene.participating_characters),
                    scene.pov_character,
                ]
            )
            overlap = len(self._terms(requirement).intersection(self._terms(source)))
            character_bonus = 3 if character and character in source else 0
            return overlap + character_bonus, -scene.scene_index

        return max(beats, key=score)

    def _obligation(
        self,
        constraint_type: str,
        requirement: str,
        scene_index: int,
        severity: Severity,
        mode: str,
    ) -> SceneObligation:
        raw = f"{constraint_type}|{requirement}|{scene_index}|{mode}".encode("utf-8")
        return SceneObligation(
            id=hashlib.sha1(raw).hexdigest()[:12],
            constraint_type=constraint_type,
            requirement=requirement,
            scene_index=scene_index,
            severity=severity,
            mode=mode,
        )

    def _knowledge_requirements(self, contract: ChapterContract) -> list[tuple[str, str, str]]:
        values: list[tuple[str, str, str]] = []
        for character in sorted(contract.knowledge_boundaries):
            boundaries = contract.knowledge_boundaries.get(character) or {}
            for raw_kind, facts in sorted(boundaries.items()):
                kind = self._knowledge_kind(raw_kind)
                clean_facts = self._unique(facts)
                # Contract JSON generated from natural-language cases commonly
                # arrives as {"知道某事": ["true"]} or {"不知某事": []}.
                # The key is the fact in that representation, not the literal
                # string "true" (which otherwise creates duplicate, unusable
                # obligations). Preserve the canonical bucket form such as
                # {"可以获得": ["姐姐的录音"]} unchanged.
                if self._is_fact_key(raw_kind, clean_facts):
                    fact = self._fact_from_key(raw_kind)
                    if fact:
                        values.append((character, kind, fact))
                    continue
                for fact in clean_facts:
                    values.append((character, kind, fact))
        return values

    @classmethod
    def _is_fact_key(cls, raw_kind: str, facts: list[str]) -> bool:
        normalized = cls._clean(raw_kind)
        flag_values = {"true", "false", "是", "否", "已知", "未知"}
        if facts and all(cls._clean(value) in flag_values for value in facts):
            return True
        if facts:
            return False
        return not cls._is_knowledge_bucket(normalized)

    @staticmethod
    def _is_knowledge_bucket(normalized: str) -> bool:
        return normalized in {
            "可以获得",
            "可获得",
            "获得",
            "acquire",
            "learn",
            "gain",
            "不应知道",
            "不能知道",
            "不得知道",
            "未知",
            "forbidden",
            "unknown",
            "知道",
            "知晓",
            "已知",
            "known",
        }

    @staticmethod
    def _fact_from_key(raw_kind: str) -> str:
        return re.sub(
            r"^(?:可以获得|可获得|获得|知晓|知道|已知|不应知道|不能知道|不得知道|不知道|不知|未知)[:：]?",
            "",
            raw_kind.strip(),
        ).strip()

    def _knowledge_kind(self, key: str) -> str:
        normalized = re.sub(r"[_\W]+", "", key, flags=re.UNICODE).lower()
        if any(token in normalized for token in ("acquire", "learn", "gain", "可以获得", "获得")):
            return "acquisition"
        if any(
            token in normalized
            for token in (
                "forbidden",
                "unknown",
                "cannotknow",
                "mustnotknow",
                "不应知道",
                "不能知道",
                "不得知道",
                "不知道",
                "不知",
                "未知",
            )
        ):
            return "forbidden"
        return "known"

    @staticmethod
    def _knowledge_requirement_label(character: str, kind: str, information: str) -> str:
        if kind == "acquisition":
            return f"{character} 可以通过剧情获得: {information}"
        if kind == "forbidden":
            return f"{character} 不应知道: {information}"
        return f"{character} 应已知道: {information}"

    def _failure_category(
        self,
        obligation: SceneObligation,
        check: ConstraintCheck | None,
        passed: bool,
    ) -> str:
        if passed:
            return ""
        if check is None:
            return "missing_check"
        if check.status is CheckStatus.REVIEW_REQUIRED:
            return "insufficient_evidence"
        if obligation.constraint_type == "must_not_happen":
            return "prohibited_action"
        if obligation.constraint_type.startswith("knowledge"):
            return "knowledge_boundary"
        if obligation.constraint_type == "ending_hook":
            return "ending_hook"
        return "missing_required_event"

    @classmethod
    def _same_action(cls, left: str, right: str) -> bool:
        left_clean, right_clean = cls._action_clean(left), cls._action_clean(right)
        if not left_clean or not right_clean:
            return False
        if left_clean == right_clean:
            return True
        shorter, longer = sorted((left_clean, right_clean), key=len)
        return len(shorter) >= 4 and shorter in longer

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", "", value or "").lower()

    @classmethod
    def _action_clean(cls, value: str) -> str:
        cleaned = cls._clean(value)
        cleaned = re.sub(r"在第[一二三四五六七八九十百0-9]+章(?:就)?", "", cleaned)
        return cleaned.replace("立刻", "").replace("马上", "")

    @staticmethod
    def _terms(value: str) -> set[str]:
        english = set(re.findall(r"[A-Za-z]{3,}", value.lower()))
        stop = set("的了是在有和与及或但就也都而后前中上下一这那章场景事件要求必须")
        chinese = {
            item
            for item in value
            if "\u4e00" <= item <= "\u9fff" and item not in stop
        }
        return english | chinese

    @staticmethod
    def _is_ending_requirement(requirement: str) -> bool:
        return any(token in requirement for token in ("章末", "结尾", "最后", "悬念", "未决定"))

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = value.strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

__all__ = ["ContractObligationCompiler"]
