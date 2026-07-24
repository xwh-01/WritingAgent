"""Story design and scene-planning use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from novelforge.application.commits import StoryCommitCoordinator
from novelforge.application.story_domains import DesignService, ManuscriptService, QualityService
from novelforge.core.exceptions import WorkflowError
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    Story,
    StoryStatus,
)


class PlannerPort(Protocol):
    def generate_outline(
        self,
        premise: str,
        num_chapters: int,
        *,
        story: Story | None = None,
        start_chapter: int = 1,
    ) -> list[ChapterOutline]: ...

    def generate_chapter_contract(
        self,
        story: Story,
        outline: ChapterOutline,
    ) -> ChapterContract: ...


class ScenePlannerPort(Protocol):
    def plan_scenes(
        self,
        story: Story,
        outline: ChapterOutline,
        contract: ChapterContract,
        context: str,
    ) -> list[Beat]: ...


class ContextPort(Protocol):
    def build(self, chapter_index: int, story: Story) -> str: ...


@dataclass(frozen=True)
class ContractResult:
    story: Story
    contract: ChapterContract


@dataclass(frozen=True)
class BeatsResult:
    story: Story
    chapter: Chapter


class StoryPlanningService:
    """Own creation of design artifacts; it never generates chapter prose."""

    def __init__(
        self,
        planner: PlannerPort,
        scenes: ScenePlannerPort,
        context: ContextPort,
        designs: DesignService,
        manuscripts: ManuscriptService,
        quality: QualityService,
        commits: StoryCommitCoordinator,
    ) -> None:
        self.planner = planner
        self.scenes = scenes
        self.context = context
        self.designs = designs
        self.manuscripts = manuscripts
        self.quality = quality
        self.commits = commits

    def create(
        self,
        premise: str,
        title: str,
        genre: str,
        style_guide: str,
    ) -> Story:
        story = Story(title=title, premise=premise, genre=genre, style_guide=style_guide)
        return self.commits.save(story).story

    def outline(self, story: Story, target_count: int, force: bool = False) -> Story:
        working = story.model_copy(deep=True)
        if force:
            if any(chapter.content.strip() for chapter in working.manuscript.chapters.values()):
                raise WorkflowError(
                    "Cannot replace the outline after prose has been committed. "
                    "Create a new story or edit individual contracts instead."
                )
            outlines = self.planner.generate_outline(
                working.premise,
                target_count,
                story=working,
                start_chapter=1,
            )
            self.designs.set_outlines(working, self._number(outlines, start=1))
        else:
            existing = max(
                (item.chapter_index for item in working.design.outlines),
                default=0,
            )
            if existing < target_count:
                generated = self.planner.generate_outline(
                    working.premise,
                    target_count - existing,
                    story=working,
                    start_chapter=existing + 1,
                )
                self.designs.append_outlines(
                    working,
                    self._number(generated, start=existing + 1),
                )
        working.status = StoryStatus.OUTLINED
        working.touch()
        return self.commits.save(working).story

    def ensure_contract(
        self,
        story: Story,
        chapter_index: int,
        force: bool = False,
    ) -> ContractResult:
        existing = story.design.chapter_contracts.get(chapter_index)
        if existing is not None and not force:
            return ContractResult(story, existing)
        working = story.model_copy(deep=True)
        outline = working.get_outline(chapter_index)
        contract = self.planner.generate_chapter_contract(
            working.generation_view(chapter_index),
            outline,
        )
        self.designs.save_contract(working, contract)
        if existing is not None:
            self.quality.invalidate_chapter_assessments(working, chapter_index)
        working.touch()
        canonical = self.commits.save(working).story
        return ContractResult(canonical, canonical.design.chapter_contracts[chapter_index])

    def update_contract(
        self,
        story: Story,
        chapter_index: int,
        contract: ChapterContract,
    ) -> ContractResult:
        working = story.model_copy(deep=True)
        working.get_outline(chapter_index)
        updated = contract.model_copy(update={"chapter_index": chapter_index})
        self.designs.save_contract(working, updated)
        self.quality.invalidate_chapter_assessments(working, chapter_index)
        working.touch()
        canonical = self.commits.save(working).story
        return ContractResult(canonical, canonical.design.chapter_contracts[chapter_index])

    def plan_beats(self, story: Story, chapter_index: int) -> BeatsResult:
        working = story.model_copy(deep=True)
        outline = working.get_outline(chapter_index)
        contract = working.design.chapter_contracts.get(chapter_index)
        if contract is None:
            contract = self.planner.generate_chapter_contract(
                working.generation_view(chapter_index),
                outline,
            )
            self.designs.save_contract(working, contract)
        source = working.generation_view(chapter_index)
        context = self.context.build(chapter_index, source)
        beats = self.scenes.plan_scenes(source, outline, contract, context)
        chapter = working.get_chapter(chapter_index) or Chapter(
            index=chapter_index,
            title=outline.title,
        )
        chapter.beats = beats
        self.manuscripts.save_chapter(working, chapter)
        working.status = StoryStatus.BEATS_READY
        working.touch()
        canonical = self.commits.save(working).story
        return BeatsResult(canonical, canonical.require_chapter(chapter_index))

    @staticmethod
    def _number(outlines: list[ChapterOutline], start: int) -> list[ChapterOutline]:
        return [
            outline.model_copy(update={"chapter_index": index})
            for index, outline in enumerate(outlines, start=start)
        ]


__all__ = ["BeatsResult", "ContractResult", "StoryPlanningService"]
