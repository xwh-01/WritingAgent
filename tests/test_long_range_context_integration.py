from __future__ import annotations

from novelforge.core.config import AppConfig
from novelforge.domain import (
    Beat,
    Character,
    CharacterFact,
    Foreshadowing,
    TimelineEvent,
    WorldSetting,
)
from novelforge.orchestrator.engine import NovelForgeEngine


def _config(tmp_path) -> AppConfig:
    return AppConfig.model_validate(
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
            "generation": {"min_quality_score": 6.0, "max_repairs": 1},
        }
    )


def test_engine_recalls_confirmed_facts_and_chapter_one_threads_for_chapter_thirty(tmp_path) -> None:
    engine = NovelForgeEngine(_config(tmp_path))
    try:
        engine.start_new_story("守门人必须保护月纹钥匙。", "Thirty Chapters")
        engine.generate_outline(30)
        engine.upsert_character(
            Character(id="lin", name="林砚", arc="学会承担承诺", relationships={"su": "互不完全信任"})
        )
        engine.upsert_character(Character(id="su", name="苏遥"))
        engine.upsert_world_setting(
            WorldSetting(id="gate", category="rule", content="黑曜门只能由月纹钥匙开启。")
        )
        engine.upsert_character_fact(
            CharacterFact(
                character_id="lin",
                fact_type="injury",
                value="左手旧伤不能承受重物",
                valid_from_chapter=1,
                user_confirmed=True,
            )
        )
        engine.write_chapter(1)

        working = engine.current_story.model_copy(deep=True)
        working.knowledge.foreshadowings.append(
            Foreshadowing(
                id="moon-key",
                description="月纹钥匙将在黑曜门前决定林砚的承诺。",
                created_chapter=1,
                target_chapter=30,
            )
        )
        working.knowledge.timeline.append(
            TimelineEvent(
                id="promise",
                chapter=1,
                description="林砚答应苏遥在黑曜门前交出旧钟。",
            )
        )
        working.touch()
        engine.story = engine.commits.save_and_reindex(
            working,
            event_type="test_remote_context_seeded",
        ).story

        scene = Beat(
            scene_index=1,
            title="黑曜门前",
            purpose="兑现钥匙承诺",
            goal="决定是否交出旧钟",
            outcome="承诺被重新检验",
            obstacle="左手旧伤与苏遥的不信任",
            location="黑曜门",
            participating_characters=["林砚", "苏遥"],
            character_goals={"林砚": "守住钥匙", "苏遥": "要求兑现承诺"},
        )
        source = engine.current_story.generation_view(30)
        context = engine.writing_context.build_scene_context(30, source, scene)

        assert "左手旧伤不能承受重物" in context.content
        assert "黑曜门只能由月纹钥匙开启" in context.content
        assert "月纹钥匙将在黑曜门前决定林砚的承诺" in context.content
        assert "林砚答应苏遥在黑曜门前交出旧钟" in context.content
        assert any(label == "角色关系图" for label in context.stats["selected_labels"])
    finally:
        engine.close()


def test_engine_reconciles_scene_state_after_the_real_polish_stage(tmp_path) -> None:
    config = _config(tmp_path)
    config.story.auto_polish_drafts = True
    engine = NovelForgeEngine(config)
    try:
        engine.start_new_story("一个人必须在真相和家人之间选择。", "Polish State")
        engine.generate_outline(1)
        chapter = engine.write_chapter(1)

        assert chapter.content
        assert chapter.beats[0].end_state["ending_state"]["grounded_in"] == "polished"
    finally:
        engine.close()
