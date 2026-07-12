"""Pydantic domain models for long-form fiction projects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


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


class ChapterContract(BaseModel):
    """用户可编辑的章节执行合同，是正文生成和验收的硬约束来源。"""

    chapter_index: int
    pov_character: str | None = None
    location: str = ""
    time_context: str = ""
    must_happen: list[str] = Field(default_factory=list)
    must_not_happen: list[str] = Field(default_factory=list)
    character_goals: dict[str, str] = Field(default_factory=dict)
    knowledge_boundaries: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    active_threads: list[str] = Field(default_factory=list)
    ending_hook: str = ""
    style_requirements: list[str] = Field(default_factory=list)
    notes: str = ""


class ConstraintCheck(BaseModel):
    """章节合同中一项硬约束的验收结果。"""

    constraint_type: str
    requirement: str
    passed: bool
    severity: str = "high"
    evidence: str = ""
    message: str = ""
    status: str = "passed"
    rule_passed: bool | None = None
    semantic_passed: bool | None = None
    confidence: float = 0.0
    paragraph_range: str = ""
    validation_method: str = "rule"


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
    contract_checks: list[ConstraintCheck] = Field(default_factory=list)
    hard_constraints_passed: bool = True

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


class DirectorTask(BaseModel):
    """Director 计划中的一个可追踪任务。"""

    id: str = Field(default_factory=lambda: f"task-{uuid4().hex[:10]}")
    description: str
    success_criteria: list[str] = Field(default_factory=list)
    status: str = "pending"
    selected_tool: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 3
    observation: str = ""
    evaluation: "TaskEvaluation | None" = None


class CriterionResult(BaseModel):
    """单条成功标准的验收结果和证据。"""

    criterion: str
    passed: bool
    evidence: str = ""


class TaskEvaluation(BaseModel):
    """工具执行结果相对于任务目标的结构化验收。"""

    passed: bool
    criterion_results: list[CriterionResult] = Field(default_factory=list)
    recoverable: bool = True
    recommended_action: str = "complete"
    feedback: str = ""


class DirectorPlan(BaseModel):
    """Director 围绕用户目标维护的持久化执行计划。"""

    objective: str
    success_criteria: list[str] = Field(default_factory=list)
    tasks: list[DirectorTask] = Field(default_factory=list)
    status: str = "planned"
    assumptions: list[str] = Field(default_factory=list)
    replan_count: int = 0
    max_replans: int = 2


class UserQuestion(BaseModel):
    """会阻塞任务执行的结构化用户问题。"""

    id: str = Field(default_factory=lambda: f"question-{uuid4().hex[:10]}")
    question: str
    reason: str = ""
    options: list[str] = Field(default_factory=list)
    required_for_task: str = ""
    answer: str | None = None


class RevisionProposal(BaseModel):
    """尚未覆盖正式正文的章节修订候选。"""

    id: str = Field(default_factory=lambda: f"proposal-{uuid4().hex[:12]}")
    story_id: str
    chapter_index: int
    source_version: int
    instruction: str
    original_content: str
    proposed_content: str
    review_report: ReviewReport
    validation_report: ReviewReport
    status: str = "awaiting_approval"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentTraceRun(BaseModel):
    """Agent 一次完整运行的追踪记录，汇聚所有步骤和最终摘要。"""

    id: str
    story_id: str
    user_message: str
    status: str = "running"
    steps: list[AgentTraceStep] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)
    final_summary: str = ""
    pending_question: str = ""
    pending_user_question: UserQuestion | None = None
    user_responses: list[str] = Field(default_factory=list)
    plan: DirectorPlan | None = None
    proposal_ids: list[str] = Field(default_factory=list)
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


class CharacterContinuityIssue(BaseModel):
    """角色在跨章节轨迹中出现的不连续或缺少过渡的证据。"""

    chapter_index: int
    dimension: str
    severity: str = "medium"
    description: str
    evidence: str = ""
    suggestion: str = ""
    previous_chapter: int | None = None


class CharacterContinuityReport(BaseModel):
    """一位角色在指定章节范围内的人设、知识、地点和关系轨迹审计。"""

    character_id: str
    character_name: str = ""
    start_chapter: int
    end_chapter: int
    trajectory: list[CharacterState] = Field(default_factory=list)
    issues: list[CharacterContinuityIssue] = Field(default_factory=list)
    affected_chapters: list[int] = Field(default_factory=list)
    passed: bool = True
    summary: str = ""


class CharacterFact(BaseModel):
    """带生效区间和来源的人物事实，可由系统提取或用户确认。"""

    id: str = Field(default_factory=lambda: f"fact-{uuid4().hex[:12]}")
    character_id: str
    fact_type: str
    value: str
    valid_from_chapter: int
    valid_until_chapter: int | None = None
    source_chapter: int | None = None
    confidence: float = 1.0
    user_confirmed: bool = False
    notes: str = ""


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


class StoryContent(BaseModel):
    """Canonical creative material: source entities, plans, contracts, and chapter versions."""

    characters: dict[str, Character] = Field(default_factory=dict)
    world_settings: list[WorldSetting] = Field(default_factory=list)
    outlines: list[ChapterOutline] = Field(default_factory=list)
    chapter_contracts: dict[int, ChapterContract] = Field(default_factory=dict)
    chapters: dict[int, Chapter] = Field(default_factory=dict)


class StoryMemory(BaseModel):
    """Long-form facts and recall material derived from approved story content."""

    facts: list[CharacterFact] = Field(default_factory=list)
    states: dict[str, list[CharacterState]] = Field(default_factory=dict)
    foreshadowings: list[Foreshadowing] = Field(default_factory=list)
    causal_events: list[CausalEvent] = Field(default_factory=list)
    chapter_summaries: dict[int, ChapterSummary] = Field(default_factory=dict)
    volume_summaries: list[VolumeSummary] = Field(default_factory=list)
    arc_summaries: list[ArcSummary] = Field(default_factory=list)
    story_bible: StoryBible = Field(default_factory=StoryBible)
    cards: list[MemoryCard] = Field(default_factory=list)


class StoryQuality(BaseModel):
    """Reviews, continuity diagnostics, and approval-gated candidate changes."""

    auto_revision_reports: dict[int, AutoRevisionReport] = Field(default_factory=dict)
    continuity_reports: dict[int, ContinuityAuditReport] = Field(default_factory=dict)
    character_continuity_reports: list[CharacterContinuityReport] = Field(default_factory=list)
    revision_proposals: list[RevisionProposal] = Field(default_factory=list)


class StoryAgentRuns(BaseModel):
    """Persistent agent execution records, plans, tasks, questions, evaluations, and traces."""

    autonomous: list[AutonomousRunReport] = Field(default_factory=list)
    director: list[AgentTraceRun] = Field(default_factory=list)
    batch_reports: list[BatchWriteReport] = Field(default_factory=list)


class Story(BaseModel):
    """Root aggregate with explicit content, memory, quality, and agent-run ownership boundaries."""

    id: UUID = Field(default_factory=uuid4)
    title: str
    premise: str
    genre: str = "novel"
    style_guide: str = ""
    content: StoryContent = Field(default_factory=StoryContent)
    memory: StoryMemory = Field(default_factory=StoryMemory)
    quality: StoryQuality = Field(default_factory=StoryQuality)
    agent_runs: StoryAgentRuns = Field(default_factory=StoryAgentRuns)
    current_chapter: int = 0
    status: str = "planning"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_story_state(cls, value: Any) -> Any:
        """Read old flat JSON documents while writing only the explicit four-domain structure."""
        if not isinstance(value, dict) or all(key in value for key in ("content", "memory", "quality", "agent_runs")):
            return value
        data = dict(value)
        content_fields = ("characters", "world_settings", "outlines", "chapter_contracts", "chapters")
        memory_map = {
            "character_facts": "facts", "character_states": "states", "foreshadowings": "foreshadowings",
            "causal_events": "causal_events", "chapter_summaries": "chapter_summaries",
            "volume_summaries": "volume_summaries", "arc_summaries": "arc_summaries",
            "story_bible": "story_bible", "memory_cards": "cards",
        }
        quality_fields = ("auto_revision_reports", "continuity_reports", "character_continuity_reports", "revision_proposals")
        old_autonomous = data.pop("agent_runs", [])
        old_director = data.pop("agent_trace_runs", [])
        old_batch = data.pop("batch_reports", [])
        data["content"] = {name: data.pop(name) for name in content_fields if name in data}
        data["memory"] = {target: data.pop(source) for source, target in memory_map.items() if source in data}
        data["quality"] = {name: data.pop(name) for name in quality_fields if name in data}
        data["agent_runs"] = {"autonomous": old_autonomous, "director": old_director, "batch_reports": old_batch}
        return data

    # Compatibility aliases keep the existing public API stable while internal callers migrate
    # to story.content / story.memory / story.quality / story.agent_runs.
    @property
    def outlines(self) -> list[ChapterOutline]: return self.content.outlines
    @outlines.setter
    def outlines(self, value: list[ChapterOutline]) -> None: self.content.outlines = value
    @property
    def chapter_contracts(self) -> dict[int, ChapterContract]: return self.content.chapter_contracts
    @chapter_contracts.setter
    def chapter_contracts(self, value: dict[int, ChapterContract]) -> None: self.content.chapter_contracts = value
    @property
    def chapters(self) -> dict[int, Chapter]: return self.content.chapters
    @chapters.setter
    def chapters(self, value: dict[int, Chapter]) -> None: self.content.chapters = value
    @property
    def characters(self) -> dict[str, Character]: return self.content.characters
    @characters.setter
    def characters(self, value: dict[str, Character]) -> None: self.content.characters = value
    @property
    def world_settings(self) -> list[WorldSetting]: return self.content.world_settings
    @world_settings.setter
    def world_settings(self, value: list[WorldSetting]) -> None: self.content.world_settings = value
    @property
    def character_facts(self) -> list[CharacterFact]: return self.memory.facts
    @character_facts.setter
    def character_facts(self, value: list[CharacterFact]) -> None: self.memory.facts = value
    @property
    def character_states(self) -> dict[str, list[CharacterState]]: return self.memory.states
    @character_states.setter
    def character_states(self, value: dict[str, list[CharacterState]]) -> None: self.memory.states = value
    @property
    def foreshadowings(self) -> list[Foreshadowing]: return self.memory.foreshadowings
    @foreshadowings.setter
    def foreshadowings(self, value: list[Foreshadowing]) -> None: self.memory.foreshadowings = value
    @property
    def causal_events(self) -> list[CausalEvent]: return self.memory.causal_events
    @causal_events.setter
    def causal_events(self, value: list[CausalEvent]) -> None: self.memory.causal_events = value
    @property
    def chapter_summaries(self) -> dict[int, ChapterSummary]: return self.memory.chapter_summaries
    @chapter_summaries.setter
    def chapter_summaries(self, value: dict[int, ChapterSummary]) -> None: self.memory.chapter_summaries = value
    @property
    def volume_summaries(self) -> list[VolumeSummary]: return self.memory.volume_summaries
    @volume_summaries.setter
    def volume_summaries(self, value: list[VolumeSummary]) -> None: self.memory.volume_summaries = value
    @property
    def arc_summaries(self) -> list[ArcSummary]: return self.memory.arc_summaries
    @arc_summaries.setter
    def arc_summaries(self, value: list[ArcSummary]) -> None: self.memory.arc_summaries = value
    @property
    def story_bible(self) -> StoryBible: return self.memory.story_bible
    @story_bible.setter
    def story_bible(self, value: StoryBible) -> None: self.memory.story_bible = value
    @property
    def memory_cards(self) -> list[MemoryCard]: return self.memory.cards
    @memory_cards.setter
    def memory_cards(self, value: list[MemoryCard]) -> None: self.memory.cards = value
    @property
    def auto_revision_reports(self) -> dict[int, AutoRevisionReport]: return self.quality.auto_revision_reports
    @auto_revision_reports.setter
    def auto_revision_reports(self, value: dict[int, AutoRevisionReport]) -> None: self.quality.auto_revision_reports = value
    @property
    def continuity_reports(self) -> dict[int, ContinuityAuditReport]: return self.quality.continuity_reports
    @continuity_reports.setter
    def continuity_reports(self, value: dict[int, ContinuityAuditReport]) -> None: self.quality.continuity_reports = value
    @property
    def character_continuity_reports(self) -> list[CharacterContinuityReport]: return self.quality.character_continuity_reports
    @character_continuity_reports.setter
    def character_continuity_reports(self, value: list[CharacterContinuityReport]) -> None: self.quality.character_continuity_reports = value
    @property
    def revision_proposals(self) -> list[RevisionProposal]: return self.quality.revision_proposals
    @revision_proposals.setter
    def revision_proposals(self, value: list[RevisionProposal]) -> None: self.quality.revision_proposals = value
    @property
    def batch_reports(self) -> list[BatchWriteReport]: return self.agent_runs.batch_reports
    @batch_reports.setter
    def batch_reports(self, value: list[BatchWriteReport]) -> None: self.agent_runs.batch_reports = value
    @property
    def agent_trace_runs(self) -> list[AgentTraceRun]: return self.agent_runs.director
    @agent_trace_runs.setter
    def agent_trace_runs(self, value: list[AgentTraceRun]) -> None: self.agent_runs.director = value

    def get_outline(self, chapter_index: int) -> ChapterOutline:
        """根据章节序号查找对应的大纲，找不到时抛出 KeyError。"""
        for outline in self.outlines:
            if outline.chapter_index == chapter_index:
                return outline
        raise KeyError(f"Chapter outline {chapter_index} does not exist.")

    def touch(self) -> None:
        """将 updated_at 置为当前 UTC 时间，表示故事状态已变更。"""
        self.updated_at = utc_now()
