from __future__ import annotations

from types import SimpleNamespace

from novelforge.context.writing import SceneWritingContext, WritingContextAssembler
from novelforge.domain import (
    Beat,
    Chapter,
    ChapterContract,
    ChapterOutline,
    Character,
    CharacterFact,
    CharacterState,
    Foreshadowing,
    SceneDraft,
    SceneEndState,
    Story,
    TimelineEvent,
    WorldSetting,
)
from novelforge.indexes.graph_store import NetworkXGraphStore
from novelforge.indexes.vector_store import InMemoryVectorStore
from novelforge.orchestrator.chapter_composer import ChapterComposer


class _UnusedTextStore:
    def search(self, *args, **kwargs):
        return []


def _remote_story() -> tuple[Story, Beat]:
    story = Story(title="Long Recall", premise="A courier protects a sealed truth.")
    story.design.characters = {
        "lin": Character(id="lin", name="林砚", personality="谨慎", motivation="守住真相"),
        "su": Character(id="su", name="苏遥", personality="敏锐", motivation="追查真相"),
    }
    story.design.world_settings = [
        WorldSetting(id="obsidian-gate", category="rule", content="黑曜门只能用月纹钥匙开启。")
    ]
    story.knowledge.character_facts = [
        CharacterFact(
            character_id="lin",
            fact_type="injury",
            value="左手旧伤不能承受重物",
            valid_from_chapter=1,
            source_chapter=1,
            user_confirmed=True,
        )
    ]
    story.knowledge.character_states = {
        "lin": [
            CharacterState(
                character_id="lin",
                chapter=1,
                location="北港",
                knowledge_gained=["月纹钥匙藏在旧钟内"],
            )
        ]
    }
    story.knowledge.foreshadowings = [
        Foreshadowing(
            id="moon-key",
            description="月纹钥匙的锯齿对应黑曜门机关。",
            created_chapter=1,
            target_chapter=30,
        )
    ]
    story.knowledge.timeline = [
        TimelineEvent(
            id="clock-promise",
            chapter=1,
            description="林砚答应苏遥在黑曜门前交出旧钟。",
        )
    ]
    scene = Beat(
        scene_index=1,
        title="门前交接",
        purpose="在黑曜门前决定是否交出月纹钥匙",
        goal="交出旧钟",
        outcome="两人必须共同面对机关",
        obstacle="左手旧伤与互不信任",
        location="黑曜门",
        participating_characters=["林砚", "苏遥"],
        character_goals={"林砚": "守住钥匙", "苏遥": "取得旧钟"},
    )
    return story, scene


def test_scene_context_recalls_chapter_one_facts_at_chapter_thirty(tmp_path) -> None:
    story, scene = _remote_story()
    vector = InMemoryVectorStore()
    graph = NetworkXGraphStore(str(tmp_path / "graph"))
    story_id = str(story.id)
    lin_node = f"{story_id}:character:lin"
    su_node = f"{story_id}:character:su"
    graph.add_node(lin_node, {"story_id": story_id, "name": "林砚"})
    graph.add_node(su_node, {"story_id": story_id, "name": "苏遥"})
    graph.add_edge(lin_node, su_node, "互不完全信任")
    vector.add(
        "knowledge_notes",
        ["第1章：月纹钥匙藏在旧钟内，不能落入陌生人手中。"],
        [{"story_id": story_id, "type": "foreshadowing", "chapter": 1, "entities": "lin"}],
        [f"{story_id}:note:moon-key"],
    )
    vector.add(
        "character_facts",
        ["过期事实：林砚已经失去月纹钥匙。", "未确认事实：林砚其实从未受伤。"],
        [
            {
                "story_id": story_id,
                "type": "character_fact",
                "chapter": 1,
                "confirmed": True,
                "valid_until_chapter": 2,
            },
            {
                "story_id": story_id,
                "type": "character_fact",
                "chapter": 1,
                "confirmed": False,
                "valid_until_chapter": 0,
            },
        ],
        [f"{story_id}:fact:expired", f"{story_id}:fact:unconfirmed"],
    )

    context = WritingContextAssembler(
        vector,
        _UnusedTextStore(),
        max_context_tokens=6000,
        graph_store=graph,
    ).build_scene_context(30, story, scene)

    assert "左手旧伤不能承受重物" in context.content
    assert "黑曜门只能用月纹钥匙开启" in context.content
    assert "月纹钥匙的锯齿对应黑曜门机关" in context.content
    assert "林砚答应苏遥在黑曜门前交出旧钟" in context.content
    assert "互不完全信任" in context.content
    assert "过期事实" not in context.content
    assert "未确认事实" not in context.content
    assert "第1章正式正文" in context.content
    assert context.stats["chapter_index"] == 30
    assert context.stats["selected_evidence_count"] >= 5


class _StaticContextBuilder:
    def build_scene_context(self, chapter_index, story, scene):
        return SceneWritingContext(
            chapter_index=chapter_index,
            scene_index=scene.scene_index,
            query="远距事实",
            content="[已确认角色事实] 左手旧伤不能承受重物",
            evidence=(),
            stats={},
        )


class _CapturingWriter:
    def __init__(self) -> None:
        self.scene_context = ""
        self.reconciled_content = ""

    def write_scene(self, **kwargs):
        self.scene_context = kwargs["scene_context"]
        return SceneDraft(
            content="初稿正文",
            ending_state=SceneEndState(location_changes={"林砚": "旧地点"}),
        )

    def reconcile_scene_end_state(self, *, content, scene, previous_scene_end_state):
        self.reconciled_content = content
        return SceneEndState(
            location_changes={"林砚": "润色后的地点"},
            ending_state={"grounded_in": "final_prose"},
        )


def test_composer_passes_scene_context_and_reconciles_state_after_polish() -> None:
    story, scene = _remote_story()
    story.design.outlines = [
        ChapterOutline(
            chapter_index=30,
            title="门前交接",
            summary="远距事实回收。",
            conflict="信任与责任冲突。",
            pov_character="林砚",
        )
    ]
    contract = ChapterContract(chapter_index=30)
    story.manuscript.chapters[30] = Chapter(index=30, title="门前交接", beats=[scene])
    writer = _CapturingWriter()
    composer = ChapterComposer(
        planner=SimpleNamespace(),
        writer=writer,
        target_length=800,
        scene_context_builder=_StaticContextBuilder(),
    )

    candidate = composer.compose(
        story,
        story.get_outline(30),
        contract,
        "chapter planning context",
        lambda *_: "润色后的正文",
    )

    assert "左手旧伤不能承受重物" in writer.scene_context
    assert writer.reconciled_content == "润色后的正文"
    assert candidate.beats[0].end_state["location_changes"]["林砚"] == "润色后的地点"
    assert candidate.beats[0].end_state["ending_state"]["grounded_in"] == "final_prose"
