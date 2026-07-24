from __future__ import annotations

import pytest

from novelforge.agents.base import BaseAgent
from novelforge.application.generation import (
    CandidateEvaluator,
    ChapterGenerationPipeline,
    GenerationPolicy,
)
from novelforge.core.config import AppConfig
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    CheckStatus,
    ConstraintCheck,
    ContinuityAuditReport,
    QualityReviewReport,
    QualityScores,
    SceneCandidateSelection,
    SceneEndState,
    ScenePatch,
    content_digest,
)
from novelforge.llm.mock_client import MockLLMClient
from novelforge.orchestrator.chapter_composer import ChapterComposer
from novelforge.orchestrator.engine import NovelForgeEngine


def _chapter() -> Chapter:
    chapter = Chapter(
        index=1,
        title="Patch test",
        beats=[
            Beat(scene_index=1, title="One", content="原场景", participating_characters=["林砚"]),
            Beat(scene_index=2, title="Two", content="后续场景", participating_characters=["苏遥"]),
        ],
    )
    chapter.sync_content_from_scenes()
    return chapter


def test_scene_patch_is_atomic_stale_safe_and_rebuilds_chapter() -> None:
    chapter = _chapter()
    first = chapter.beats[0]
    chapter.apply_scene_patches(
        [
            ScenePatch(
                scene_index=1,
                content="修订后的场景",
                ending_state=SceneEndState(decisions={"林砚": "递交证词"}),
                source_content_digest=content_digest(first.content),
            )
        ]
    )

    assert chapter.scene_content_is_current()
    assert chapter.content == "修订后的场景\n\n***\n\n后续场景"
    assert chapter.beats[1].content == "后续场景"
    assert chapter.beats[0].end_state["decisions"] == {"林砚": "递交证词"}

    snapshot = chapter.model_dump_json()
    with pytest.raises(ValueError, match="stale"):
        chapter.apply_scene_patches(
            [
                ScenePatch(
                    scene_index=1,
                    content="过期覆盖",
                    source_content_digest=content_digest("原场景"),
                )
            ]
        )
    assert chapter.model_dump_json() == snapshot


def test_composer_reconciles_multi_scene_patches_in_order() -> None:
    class Writer:
        def reconcile_scene_end_state(self, *, content, scene, previous_scene_end_state):
            inherited = "" if previous_scene_end_state is None else previous_scene_end_state.decisions.get("flow", "")
            return SceneEndState(decisions={"flow": f"{inherited}>{content}"})

    composer = ChapterComposer(planner=None, writer=Writer(), target_length=300)
    chapter = _chapter()
    result = composer.apply_scene_patches(
        chapter,
        [
            ScenePatch(scene_index=1, content="一"),
            ScenePatch(scene_index=2, content="二"),
        ],
    )

    assert result.scene_content_is_current()
    assert result.beats[0].end_state["decisions"]["flow"] == ">一"
    assert result.beats[1].end_state["decisions"]["flow"] == ">一>二"


def test_contract_repair_uses_a_patch_with_its_own_end_state(planned_story) -> None:
    class Editor:
        def revise_scene_patch_from_contract_evidence(self, scene, _failures, _style_guide):
            return ScenePatch(
                scene_index=scene.scene_index,
                content="已补足合同的场景",
                ending_state=SceneEndState(decisions={"主角": "完成合同动作"}),
                reason="test",
            )

    class Writer:
        def reconcile_scene_end_state(self, **_kwargs):
            raise AssertionError("A structured repair must not re-extract its end state.")

    chapter = _chapter()
    chapter.beats[0].contract_obligations = [{"id": "obligation-1"}]
    composer = ChapterComposer(planner=None, writer=Writer(), editor=Editor(), target_length=300)
    ledger = type(
        "Ledger",
        (),
        {
            "failed_entries": [
                type(
                    "Entry",
                    (),
                    {
                        "scene_index": 1,
                        "model_dump": lambda self, **_kwargs: {"obligation_id": "obligation-1"},
                    },
                )()
            ]
        },
    )()

    repaired = composer.repair_contract_failures(planned_story, chapter, ledger)

    assert repaired.scene_content_is_current()
    assert repaired.beats[0].content == "已补足合同的场景"
    assert repaired.beats[0].end_state["decisions"] == {"主角": "完成合同动作"}


class _Context:
    def build(self, _chapter_index, _story):
        return "story context"


class _Contracts:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, content, _contract):
        self.calls.append(content)
        if "UNSAFE" in content:
            return [
                ConstraintCheck(
                    constraint_type="must_not_happen",
                    requirement="不得出现 UNSAFE",
                    passed=False,
                    status=CheckStatus.FAILED,
                    severity="critical",
                )
            ]
        return []


class _Continuity:
    def __init__(self) -> None:
        self.local_calls: list[tuple[int, ...]] = []

    def audit_chapter(self, _story, chapter_index, _content, _context):
        return ContinuityAuditReport(chapter_index=chapter_index, passed=True)

    def audit_local_patch(self, _story, _candidate, changed_scene_indexes, _context):
        self.local_calls.append(tuple(changed_scene_indexes))
        return ContinuityAuditReport(
            chapter_index=1,
            passed=True,
            audit_method="test_local_patch",
        )


class _Critic:
    def review_quality_scorecard(self, _content, _outline, _story, extra_context=""):
        return QualityReviewReport(scores=QualityScores(
            logic_consistency=9,
            character_fidelity=9,
            foreshadowing_handling=9,
            pacing=9,
            style_uniformity=9,
        ))

    def select_scene_candidate(self, *, scene, candidates, **_kwargs):
        selected = next(key for key, content in candidates.items() if "表现稿" in content)
        return SceneCandidateSelection(scene_index=scene.scene_index, selected_id=selected, reason="more vivid")


class _RejectingSelector(_Critic):
    def select_scene_candidate(self, **_kwargs):
        raise AssertionError("A hard-failing candidate must not reach the quality selector.")


class _SearchComposer:
    def __init__(self, alternative: str) -> None:
        self.alternative = alternative
        self.requested_indexes: list[int] = []

    def apply_scene_patches(self, candidate, patches):
        updated = candidate.model_copy(deep=True)
        updated.apply_scene_patches(patches)
        return updated

    def generate_scene_quality_patches(self, _story, _outline, _contract, candidate, scene_indexes, **_kwargs):
        self.requested_indexes.extend(scene_indexes)
        scene = next(item for item in candidate.beats if item.scene_index == scene_indexes[0])
        return {
            scene.scene_index: [
                ScenePatch(
                    scene_index=scene.scene_index,
                    content=self.alternative,
                    ending_state=SceneEndState(decisions={"林砚": "继续"}),
                    source_content_digest=content_digest(scene.content),
                )
            ]
        }


class _Editor:
    def revise_from_quality_report(self, content, _report, style_guide=""):
        return content


def _search_pipeline(composer, contracts, continuity, critic) -> ChapterGenerationPipeline:
    return ChapterGenerationPipeline(
        composer=composer,
        context=_Context(),
        evaluator=CandidateEvaluator(
            contracts=contracts,
            continuity=continuity,
            critic=critic,
            policy=GenerationPolicy(
                quality_search_enabled=True,
                quality_search_max_scenes=1,
                quality_search_candidates=2,
                auto_repair_review_issues=False,
            ),
        ),
        editor=_Editor(),
    )


def test_quality_search_hard_gates_then_blind_selects_and_locally_audits(planned_story) -> None:
    composer = _SearchComposer("表现稿：雨声压低了林砚的呼吸。")
    contracts = _Contracts()
    continuity = _Continuity()
    outcome = _search_pipeline(composer, contracts, continuity, _Critic()).gate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        _chapter(),
    )

    assert outcome.accepted is True
    assert outcome.candidate.beats[1].content.startswith("表现稿")
    assert outcome.candidate.scene_content_is_current()
    assert outcome.candidate_selections
    assert continuity.local_calls == [(2,)]
    assert any("表现稿" in content for content in contracts.calls)


def test_quality_search_drops_hard_failing_alternative_before_selection(planned_story) -> None:
    composer = _SearchComposer("UNSAFE 表现稿")
    outcome = _search_pipeline(composer, _Contracts(), _Continuity(), _RejectingSelector()).gate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        _chapter(),
    )

    assert outcome.accepted is True
    assert outcome.candidate.beats[1].content == "后续场景"
    assert not outcome.candidate_selections


def test_quality_search_safely_skips_when_budget_cannot_cover_search_and_local_audit(planned_story) -> None:
    composer = _SearchComposer("表现稿")
    pipeline = _search_pipeline(composer, _Contracts(), _Continuity(), _Critic())
    pipeline.evaluator = CandidateEvaluator(
        contracts=_Contracts(),
        continuity=_Continuity(),
        critic=_Critic(),
        policy=GenerationPolicy(
            max_generation_calls=2,
            max_generation_tokens=10_000,
            quality_search_enabled=True,
            quality_search_max_scenes=1,
            quality_search_candidates=2,
            auto_repair_review_issues=False,
        ),
    )

    outcome = pipeline.gate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        _chapter(),
    )

    assert outcome.accepted is True
    assert composer.requested_indexes == []
    assert not outcome.candidate_selections


def test_generation_budget_rejects_before_a_second_provider_call(planned_story) -> None:
    class BudgetAgent(BaseAgent):
        def call(self):
            return self._chat("budget test", "budget test")

    class BudgetComposer:
        def __init__(self) -> None:
            self.agent = BudgetAgent(MockLLMClient())

        def compose(self, *_args, **_kwargs):
            self.agent.call()
            self.agent.call()
            return _chapter()

    pipeline = _search_pipeline(BudgetComposer(), _Contracts(), _Continuity(), _Critic())
    pipeline.evaluator = CandidateEvaluator(
        contracts=_Contracts(),
        continuity=_Continuity(),
        critic=_Critic(),
        policy=GenerationPolicy(
            max_generation_calls=1,
            max_generation_tokens=10_000,
            quality_search_enabled=False,
        ),
    )
    outcome = pipeline.generate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        lambda *_args: "",
    )

    assert outcome.accepted is False
    assert outcome.budget is not None
    assert outcome.budget.calls_used == 1
    assert outcome.budget.exhausted_reason == "max_calls"
    assert outcome.final_assessment.reasons == ("budget:exhausted",)


def test_generation_token_budget_blocks_an_oversized_prompt_before_provider_use(planned_story) -> None:
    class BudgetAgent(BaseAgent):
        def call(self):
            return self._chat("token budget", "x" * 600)

    class TokenBudgetComposer:
        def __init__(self) -> None:
            self.agent = BudgetAgent(MockLLMClient())

        def compose(self, *_args, **_kwargs):
            self.agent.call()
            return _chapter()

    pipeline = _search_pipeline(TokenBudgetComposer(), _Contracts(), _Continuity(), _Critic())
    pipeline.evaluator = CandidateEvaluator(
        contracts=_Contracts(),
        continuity=_Continuity(),
        critic=_Critic(),
        policy=GenerationPolicy(
            max_generation_calls=8,
            max_generation_tokens=50,
            quality_search_enabled=False,
        ),
    )
    outcome = pipeline.generate(
        planned_story,
        planned_story.get_outline(1),
        planned_story.design.chapter_contracts[1],
        lambda *_args: "",
    )

    assert outcome.accepted is False
    assert outcome.budget is not None
    assert outcome.budget.calls_used == 0
    assert outcome.budget.exhausted_reason == "max_tokens"


def test_engine_runs_the_v04_search_selection_and_local_audit_path(tmp_path) -> None:
    config = AppConfig.model_validate(
        {
            "llm": {"provider": "mock"},
            "indexes": {"vector_store": "in_memory"},
            "storage": {
                "database_path": str(tmp_path / "novelforge.db"),
                "artifact_directory": str(tmp_path / "artifacts"),
                "vector_index_directory": str(tmp_path / "vector"),
                "graph_index_directory": str(tmp_path / "graph"),
                "full_text_index_path": str(tmp_path / "fts.sqlite3"),
            },
            "story": {"auto_polish_drafts": False, "prose_target_words": 500},
            "generation": {
                "min_quality_score": 6.0,
                "max_generation_calls": 12,
                "max_generation_tokens": 18_000,
                "quality_search_enabled": True,
                "quality_search_max_scenes": 1,
                "quality_search_candidates": 2,
            },
        }
    )
    engine = NovelForgeEngine(config)
    try:
        story = engine.start_new_story("主角必须在雨夜作出选择。", "v0.4 search")
        outline = ChapterOutline(chapter_index=1, title="雨夜", summary="作出选择", conflict="时间不够")
        contract = ChapterContract(chapter_index=1)
        engine.current_story.design.outlines = [outline]
        engine.current_story.design.chapter_contracts = {1: contract}

        outcome = engine.generation.generate(story, outline, contract, engine._polish_draft)

        assert outcome.accepted is True
        assert outcome.candidate.scene_content_is_current()
        assert outcome.candidate_selections
        assert outcome.assessments[-1].review_mode == "incremental_contract"
        assert outcome.assessments[-1].changed_scene_indexes
        assert outcome.assessments[-1].continuity.audit_method == "local_patch"
        assert outcome.budget is not None
        assert outcome.budget.calls_used <= outcome.budget.max_calls
    finally:
        engine.close()
