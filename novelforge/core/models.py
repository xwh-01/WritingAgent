"""Pydantic domain models for long-form fiction projects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Character(BaseModel):
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
    id: str
    category: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChapterOutline(BaseModel):
    chapter_index: int
    title: str
    summary: str
    conflict: str
    pov_character: str | None = None


class Beat(BaseModel):
    scene_index: int
    description: str
    goal: str
    outcome: str


class ChapterVersion(BaseModel):
    version: int
    content: str
    status: str
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class Chapter(BaseModel):
    index: int
    title: str
    content: str = ""
    version: int = 1
    status: str = "draft"
    summary: str = ""
    beats: list[Beat] = Field(default_factory=list)
    history: list[ChapterVersion] = Field(default_factory=list)

    def snapshot(self) -> ChapterVersion:
        return ChapterVersion(
            version=self.version,
            content=self.content,
            status=self.status,
            summary=self.summary,
        )

    def update_content(self, content: str, status: str | None = None, summary: str | None = None) -> None:
        if self.content:
            self.history.append(self.snapshot())
        self.version += 1
        self.content = content
        if status:
            self.status = status
        if summary is not None:
            self.summary = summary


class ReviewReport(BaseModel):
    logic_issues: list[str] = Field(default_factory=list)
    character_issues: list[str] = Field(default_factory=list)
    pacing_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    verdict: str = "needs_revision"


class QualityScores(BaseModel):
    logic_consistency: float = 0.0
    character_fidelity: float = 0.0
    foreshadowing_handling: float = 0.0
    pacing: float = 0.0
    style_uniformity: float = 0.0

    def weighted_total(self, weights: dict[str, float] | None = None) -> float:
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
    dimension: str
    severity: str = "medium"
    description: str


class ContinuityIssue(BaseModel):
    dimension: str
    severity: str = "medium"
    description: str
    evidence: str = ""
    suggestion: str = ""


class ContinuityAuditReport(BaseModel):
    chapter_index: int
    risk_score: float = 0.0
    passed: bool = True
    issues: list[ContinuityIssue] = Field(default_factory=list)
    checked_constraints: list[str] = Field(default_factory=list)
    summary: str = ""


class QualityReviewReport(BaseModel):
    scores: QualityScores = Field(default_factory=QualityScores)
    issues: list[RevisionIssue] = Field(default_factory=list)
    overall_comment: str = ""

    def total_score(self, weights: dict[str, float] | None = None) -> float:
        return self.scores.weighted_total(weights)


class AutoRevisionRoundReport(BaseModel):
    round: int
    review_report: QualityReviewReport
    revised_content: str = ""
    total_score: float = 0.0
    modification_summary: str = ""


class AutoRevisionReport(BaseModel):
    chapter_index: int
    final_content: str = ""
    rounds: list[AutoRevisionRoundReport] = Field(default_factory=list)
    final_score: float = 0.0
    passed: bool = False
    residual_issues: list[RevisionIssue] = Field(default_factory=list)
    stopped: bool = False
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


class BatchChapterResult(BaseModel):
    chapter_index: int
    status: str
    title: str = ""
    word_count: int = 0
    auto_revision_score: float | None = None
    message: str = ""


class BatchWriteReport(BaseModel):
    start_chapter: int
    end_chapter: int
    use_auto_revision: bool = True
    results: list[BatchChapterResult] = Field(default_factory=list)
    completed: int = 0
    failed: int = 0
    stopped: bool = False


class AgentTask(BaseModel):
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
    id: str
    description: str
    created_chapter: int
    target_chapter: int | None = None
    status: str = "pending"
    notes: str = ""


class CausalEvent(BaseModel):
    id: str
    chapter: int
    description: str
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)


class CharacterState(BaseModel):
    character_id: str
    chapter: int
    emotional_state: str = ""
    location: str = ""
    knowledge_gained: list[str] = Field(default_factory=list)
    relationship_changes: dict[str, str] = Field(default_factory=dict)


class ChapterSummary(BaseModel):
    chapter_index: int
    scene_summaries: list[str] = Field(default_factory=list)
    chapter_summary: str = ""
    key_events: list[str] = Field(default_factory=list)


class VolumeSummary(BaseModel):
    volume: int
    chapter_range: tuple[int, int]
    summary: str = ""


class ArcSummary(BaseModel):
    arc: int
    chapter_range: tuple[int, int]
    summary: str = ""
    key_threads: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class StoryBible(BaseModel):
    core_premise: str = ""
    style_guide: str = ""
    current_direction: str = ""
    active_threads: list[str] = Field(default_factory=list)
    character_roster: dict[str, str] = Field(default_factory=dict)
    world_rules: list[str] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryCard(BaseModel):
    id: str
    type: str
    content: str
    chapter: int
    importance: int = 5
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    last_seen_chapter: int | None = None


class Story(BaseModel):
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
        for outline in self.outlines:
            if outline.chapter_index == chapter_index:
                return outline
        raise KeyError(f"Chapter outline {chapter_index} does not exist.")

    def touch(self) -> None:
        self.updated_at = utc_now()
