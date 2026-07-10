"""Pydantic domain models for long-form fiction projects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """返回当前 UTC 时间戳，用作模型中 created_at / updated_at 的默认值。"""
    return datetime.now(timezone.utc)


class Character(BaseModel):
    """故事中的人物角色，包含外貌、性格、动机、弱点、人际关系弧线等属性。"""

    id: str
    name: str
    age: int | str = "unknown"
    appearance: str = ""
    personality: str = ""
    motivation: str = ""
    weakness: str = ""
    relationships: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    arc: str = ""


class WorldSetting(BaseModel):
    """世界观设定条目，按类别归类，附带元数据。"""

    id: str
    category: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChapterOutline(BaseModel):
    """章节大纲，描述第 n 章的标题、概要和核心冲突。"""

    chapter_index: int
    title: str
    summary: str
    conflict: str
    pov_character: str | None = None


class Beat(BaseModel):
    """场景节拍，定义一个场景的目标与结果。"""

    scene_index: int
    description: str
    goal: str
    outcome: str


class ChapterVersion(BaseModel):
    """章节的某个历史版本，用于追溯修改记录。"""

    version: int
    content: str
    status: str
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class Chapter(BaseModel):
    """小说中的一个章节，包含正文、节拍、版本历史等完整信息。"""

    index: int
    title: str
    content: str = ""
    version: int = 1
    status: str = "draft"
    summary: str = ""
    beats: list[Beat] = Field(default_factory=list)
    history: list[ChapterVersion] = Field(default_factory=list)

    def snapshot(self) -> ChapterVersion:
        """拍摄当前章节状态为 ChapterVersion 快照，供历史存档。"""
        return ChapterVersion(
            version=self.version,
            content=self.content,
            status=self.status,
            summary=self.summary,
        )

    def update_content(self, content: str, status: str | None = None, summary: str | None = None) -> None:
        """用新内容更新章节：先保存当前快照到历史，再递增版本号并更新字段。"""
        if self.content:
            self.history.append(self.snapshot())
        self.version += 1
        self.content = content
        if status:
            self.status = status
        if summary is not None:
            self.summary = summary


class ReviewReport(BaseModel):
    """审查报告，记录章节的逻辑、人物、节奏问题及修改建议和裁决。"""

    logic_issues: list[str] = Field(default_factory=list)
    character_issues: list[str] = Field(default_factory=list)
    pacing_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    verdict: str = "needs_revision"


class QualityScores(BaseModel):
    """多维质量评分卡，覆盖逻辑一致性、人物还原度、伏笔处理、节奏、风格统一性五个维度。"""

    logic_consistency: float = 0.0
    character_fidelity: float = 0.0
    foreshadowing_handling: float = 0.0
    pacing: float = 0.0
    style_uniformity: float = 0.0

    def weighted_total(self, weights: dict[str, float] | None = None) -> float:
        """按自定义权重计算加权平均分，默认各维度等权重。"""
        active_weights = weights or {
            "logic_consistency": 0.25,
            "character_fidelity": 0.25,
            "foreshadowing_handling": 0.20,
            "pacing": 0.15,
            "style_uniformity": 0.15,
        }
        total_weight = sum(active_weights.values()) or 1.0
        weighted = sum(getattr(self, key, 0.0) * weight for key, weight in active_weights.items())
        return round(weighted / total_weight, 2)


class RevisionIssue(BaseModel):
    """修订问题项，指明问题所属维度、严重程度、段落定位和原文证据。"""

    dimension: str
    severity: str = "medium"
    description: str
    paragraph_range: str = ""
    evidence: str = ""


class ContinuityIssue(BaseModel):
    """连续性审计中发现的问题，包含证据和建议。"""

    dimension: str
    severity: str = "medium"
    description: str
    evidence: str = ""
    suggestion: str = ""


class ContinuityAuditReport(BaseModel):
    """连续性审计报告，给出风险评分、是否通过及问题列表。"""

    chapter_index: int
    risk_score: float = 0.0
    passed: bool = True
    issues: list[ContinuityIssue] = Field(default_factory=list)
    checked_constraints: list[str] = Field(default_factory=list)
    summary: str = ""


class QualityReviewReport(BaseModel):
    """质量审查报告，汇总评分卡与问题列表，提供总体评价。"""

    scores: QualityScores = Field(default_factory=QualityScores)
    issues: list[RevisionIssue] = Field(default_factory=list)
    overall_comment: str = ""

    def total_score(self, weights: dict[str, float] | None = None) -> float:
        """返回加权综合质量分，委托给内嵌的 scores 对象计算。"""
        return self.scores.weighted_total(weights)


class AutoRevisionRoundReport(BaseModel):
    """自动修订流程中某一轮的完整记录，包含审查报告、修订后内容、分数和评分方差。"""

    round: int
    review_report: QualityReviewReport
    revised_content: str = ""
    total_score: float = 0.0
    review_score_variance: float = 0.0
    modification_summary: str = ""


class AutoRevisionReport(BaseModel):
    """自动修订的最终报告，汇总所有轮次记录、最终分数和残留问题。"""

    chapter_index: int
    final_content: str = ""
    rounds: list[AutoRevisionRoundReport] = Field(default_factory=list)
    final_score: float = 0.0
    passed: bool = False
    residual_issues: list[RevisionIssue] = Field(default_factory=list)
    stopped: bool = False
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


class BatchChapterResult(BaseModel):
    """批量生成中单个章节的结果，含状态、标题、字数和修订分。"""

    chapter_index: int
    status: str
    title: str = ""
    word_count: int = 0
    auto_revision_score: float | None = None
    message: str = ""


class BatchWriteReport(BaseModel):
    """批量撰写任务的汇总报告，记录各章节结果、完成数和失败数。"""

    start_chapter: int
    end_chapter: int
    use_auto_revision: bool = True
    results: list[BatchChapterResult] = Field(default_factory=list)
    completed: int = 0
    failed: int = 0
    stopped: bool = False


class AgentTask(BaseModel):
    """Agent 执行计划中的单个任务，记录执行状态、起止时间和元数据。"""

    id: str
    step_index: int
    agent: str
    action: str
    reason: str = ""
    chapter_index: int | None = None
    status: str = "pending"
    input_summary: str = ""
    output_summary: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomousRunReport(BaseModel):
    """Agent 自主运行的完整报告，包括目标、规划策略、任务列表和完成统计。"""

    id: str
    objective: str
    start_chapter: int
    end_chapter: int
    use_auto_revision: bool = True
    planning_strategy: str = "rule"
    planning_notes: str = ""
    status: str = "planned"
    tasks: list[AgentTask] = Field(default_factory=list)
    completed_tasks: int = 0
    failed_tasks: int = 0
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentDecision(BaseModel):
    """Agent 单步决策，描述选择的工具、参数、意图和是否继续的标志。"""

    step: int
    intent: str = ""
    selected_tool: str
    reasoning_summary: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    should_continue: bool = False
    user_message: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    fallback_action: str = ""
    reflection: str = ""
    retry_count: int = 0


class AgentTraceStep(BaseModel):
    """Agent 执行链路中的每一步详细记录，含耗时、评分变化和错误信息。"""

    step: int
    run_id: str = ""
    story_id: str = ""
    chapter_index: int | None = None
    stage: str = "director_step"
    action: str = ""
    selected_tool: str
    reasoning_summary: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    input_summary: str = ""
    output_summary: str = ""
    observation: str = ""
    memory_hits_count: int = 0
    review_score_before: float | None = None
    review_score_after: float | None = None
    success: bool = True
    error_type: str = ""
    error_message: str = ""
    duration_ms: int = 0
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class AgentTraceRun(BaseModel):
    """Agent 一次完整运行的追踪记录，汇聚所有步骤和最终摘要。"""

    id: str
    story_id: str
    user_message: str
    status: str = "running"
    steps: list[AgentTraceStep] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)
    final_summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Foreshadowing(BaseModel):
    """伏笔记录，标明创建章节、目标章节和当前状态。"""

    id: str
    description: str
    created_chapter: int
    target_chapter: int | None = None
    status: str = "pending"
    notes: str = ""


class CausalEvent(BaseModel):
    """因果事件节点，记录事件所在章节及其前因和后果。"""

    id: str
    chapter: int
    description: str
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)


class CharacterState(BaseModel):
    """角色在某一章节的状态快照，含情绪、位置、知识和关系变化。"""

    character_id: str
    chapter: int
    emotional_state: str = ""
    location: str = ""
    knowledge_gained: list[str] = Field(default_factory=list)
    relationship_changes: dict[str, str] = Field(default_factory=dict)


class ChapterSummary(BaseModel):
    """某章的场景摘要合集，包含各场景摘要、整体总结和关键事件列表。"""

    chapter_index: int
    scene_summaries: list[str] = Field(default_factory=list)
    chapter_summary: str = ""
    key_events: list[str] = Field(default_factory=list)


class VolumeSummary(BaseModel):
    """卷级别摘要，描述一卷的章节范围和整体概括。"""

    volume: int
    chapter_range: tuple[int, int]
    summary: str = ""


class ArcSummary(BaseModel):
    """故事弧摘要，包含章节范围、总结、关键叙事线和未解问题。"""

    arc: int
    chapter_range: tuple[int, int]
    summary: str = ""
    key_threads: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class StoryBible(BaseModel):
    """故事圣经 / 设定集，统合核心前提、风格指南、人物名册、世界观规则和连续性约束。"""

    core_premise: str = ""
    style_guide: str = ""
    current_direction: str = ""
    active_threads: list[str] = Field(default_factory=list)
    character_roster: dict[str, str] = Field(default_factory=dict)
    world_rules: list[str] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryCard(BaseModel):
    """记忆卡片，存储一段标签化的记忆内容及其关联实体和重要性。"""

    id: str
    type: str
    content: str
    chapter: int
    importance: int = 5
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    last_seen_chapter: int | None = None


class Story(BaseModel):
    """小说的根聚合模型，包含所有章节、角色、世界观、伏笔、因果事件、记忆及报告等完整状态。"""

    id: UUID = Field(default_factory=uuid4)
    title: str
    premise: str
    genre: str = "novel"
    style_guide: str = ""
    outlines: list[ChapterOutline] = Field(default_factory=list)
    chapters: dict[int, Chapter] = Field(default_factory=dict)
    characters: dict[str, Character] = Field(default_factory=dict)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    foreshadowings: list[Foreshadowing] = Field(default_factory=list)
    causal_events: list[CausalEvent] = Field(default_factory=list)
    character_states: dict[str, list[CharacterState]] = Field(default_factory=dict)
    chapter_summaries: dict[int, ChapterSummary] = Field(default_factory=dict)
    volume_summaries: list[VolumeSummary] = Field(default_factory=list)
    arc_summaries: list[ArcSummary] = Field(default_factory=list)
    story_bible: StoryBible = Field(default_factory=StoryBible)
    memory_cards: list[MemoryCard] = Field(default_factory=list)
    auto_revision_reports: dict[int, AutoRevisionReport] = Field(default_factory=dict)
    continuity_reports: dict[int, ContinuityAuditReport] = Field(default_factory=dict)
    batch_reports: list[BatchWriteReport] = Field(default_factory=list)
    agent_runs: list[AutonomousRunReport] = Field(default_factory=list)
    agent_trace_runs: list[AgentTraceRun] = Field(default_factory=list)
    current_chapter: int = 0
    status: str = "planning"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def get_outline(self, chapter_index: int) -> ChapterOutline:
        """根据章节序号查找对应的大纲，找不到时抛出 KeyError。"""
        for outline in self.outlines:
            if outline.chapter_index == chapter_index:
                return outline
        raise KeyError(f"Chapter outline {chapter_index} does not exist.")

    def touch(self) -> None:
        """将 updated_at 置为当前 UTC 时间，表示故事状态已变更。"""
        self.updated_at = utc_now()
