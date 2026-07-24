from __future__ import annotations

import json
from types import SimpleNamespace

from novelforge.agents.planner import PlannerAgent
from novelforge.application.planning import StoryPlanningService
from novelforge.application.story_domains import DesignService, ManuscriptService, QualityService
from novelforge.domain import ChapterOutline, Character, Foreshadowing, Story


class _CaptureLLM:
    def __init__(self) -> None:
        self.prompt = ""

    def chat_completion(self, messages, **kwargs):
        self.prompt = messages[-1]["content"]
        return json.dumps(
            [
                {
                    "chapter_index": 3,
                    "title": "承接旧线索",
                    "summary": "主角必须处理第一章留下的钥匙。",
                    "conflict": "承诺与风险冲突。",
                    "pov_character": "林砚",
                }
            ],
            ensure_ascii=False,
        )


def _story_with_history() -> Story:
    story = Story(title="Continuation", premise="守门人必须守住真相。")
    story.current_chapter = 2
    story.design.outlines = [
        ChapterOutline(
            chapter_index=1,
            title="钥匙",
            summary="林砚找到钥匙。",
            conflict="秘密暴露",
            pov_character="林砚",
        ),
        ChapterOutline(
            chapter_index=2,
            title="承诺",
            summary="林砚答应苏遥。",
            conflict="信任动摇",
            pov_character="林砚",
        ),
    ]
    story.design.characters = {
        "lin": Character(id="lin", name="林砚", arc="从逃避承诺到承担代价")
    }
    story.knowledge.guide.active_threads = ["钥匙的来源"]
    story.knowledge.foreshadowings = [
        Foreshadowing(
            id="key", description="钥匙会在第三章开启石门。", created_chapter=1, target_chapter=3
        )
    ]
    return story


def test_planner_includes_existing_structure_when_extending_outline() -> None:
    llm = _CaptureLLM()
    outlines = PlannerAgent(llm).generate_outline(
        "守门人必须守住真相。",
        1,
        story=_story_with_history(),
        start_chapter=3,
    )

    assert outlines[0].title == "承接旧线索"
    assert '"existing_outlines"' in llm.prompt
    assert "钥匙的来源" in llm.prompt
    assert "从逃避承诺到承担代价" in llm.prompt
    assert "钥匙会在第三章开启石门" in llm.prompt
    assert "从第 3 章开始生成连续的 1 章" in llm.prompt


class _ContinuationPlanner:
    def __init__(self) -> None:
        self.received_story = None
        self.start_chapter = 0

    def generate_outline(self, premise, num_chapters, *, story=None, start_chapter=1):
        self.received_story = story
        self.start_chapter = start_chapter
        return [
            ChapterOutline(
                chapter_index=start_chapter + offset,
                title=f"续写 {start_chapter + offset}",
                summary="承接既有结构。",
                conflict="新阻力出现。",
                pov_character="林砚",
            )
            for offset in range(num_chapters)
        ]


class _Committer:
    def save(self, story):
        return SimpleNamespace(story=story)


def test_outline_service_passes_current_story_to_continuation_planner() -> None:
    story = _story_with_history()
    planner = _ContinuationPlanner()
    service = StoryPlanningService(
        planner=planner,
        scenes=SimpleNamespace(),
        context=SimpleNamespace(),
        designs=DesignService(),
        manuscripts=ManuscriptService(),
        quality=QualityService(),
        commits=_Committer(),
    )

    result = service.outline(story, target_count=4)

    assert planner.received_story is not None
    assert planner.received_story.design.outlines[1].title == "承诺"
    assert planner.start_chapter == 3
    assert [item.chapter_index for item in result.design.outlines] == [1, 2, 3, 4]
