"""Interactive command line interface for NovelForge."""

from __future__ import annotations

import shlex
import sys

try:
    import cmd2
except Exception:  # pragma: no cover - fallback only used without cmd2 installed
    import cmd as cmd2

from novelforge.orchestrator.engine import NovelForgeEngine
from novelforge.dashboard.data_provider import DashboardDataProvider


class NovelForgeShell(cmd2.Cmd):
    """NovelForge 交互式命令行 Shell，提供故事创建、大纲生成、章节写作、评审等全部操作命令。"""

    prompt = "novelforge> "
    intro = "NovelForge ready. Type /help for commands."

    def __init__(self, engine: NovelForgeEngine | None = None):
        """初始化 Shell 并绑定 NovelForgeEngine 实例。"""
        super().__init__()
        self.engine = engine or NovelForgeEngine()

    def onecmd(self, line: str):  # type: ignore[override]
        """解析用户输入，将 / 前缀命令规范化后交给 cmd2 处理。"""
        if line.startswith("/"):
            line = line[1:]
        if line:
            command, *rest = line.split(" ", 1)
            line = command.replace("-", "_") + (f" {rest[0]}" if rest else "")
        return super().onecmd(line)

    def do_new_story(self, line: str) -> None:
        """new_story <premise> -- create a new story."""
        premise = line.strip()
        if not premise:
            print("Usage: /new_story <premise>")
            return
        story = self.engine.start_new_story(premise=premise, title=premise[:30] or "Untitled Novel")
        print(f"Created story {story.title} ({story.id})")

    def do_load(self, line: str) -> None:
        """load <story_id> -- load saved story state."""
        story = self.engine.load_state(line.strip())
        print(f"Loaded {story.title} ({story.status})")

    def do_stories(self, line: str) -> None:
        """stories -- list saved stories."""
        records = self.engine.repository.list_records()
        if not records:
            print("No saved stories found.")
            return
        for record in records[:30]:
            print(f"{record.id} | ch{record.current_chapter} | {record.status} | {record.title}")

    def do_outline(self, line: str) -> None:
        """outline [num_chapters] -- generate chapter outline."""
        num = int(line.strip()) if line.strip() else None
        outlines = self.engine.generate_outline(num)
        for outline in outlines:
            print(f"{outline.chapter_index}. {outline.title} - {outline.summary}")

    def do_beats(self, line: str) -> None:
        """beats <n> -- generate beats for chapter n."""
        chapter = self.engine.generate_beats(int(line.strip()))
        for beat in chapter.beats:
            print(f"{beat.scene_index}. {beat.description} -> {beat.outcome}")

    def do_write(self, line: str) -> None:
        """write <n> -- draft chapter n."""
        chapter = self.engine.write_chapter(int(line.strip()))
        print(f"Wrote {chapter.title} v{chapter.version}")
        print(chapter.content[:1000])

    def do_review(self, line: str) -> None:
        """review <n> -- review chapter n."""
        report = self.engine.request_review(int(line.strip()))
        print(report.model_dump_json(indent=2))

    def do_revise(self, line: str) -> None:
        """revise <n> [manual text] -- revise chapter n."""
        parts = shlex.split(line)
        if not parts:
            print("Usage: /revise <n> [manual revised content]")
            return
        chapter_index = int(parts[0])
        manual = " ".join(parts[1:]) if len(parts) > 1 else None
        chapter = self.engine.apply_revision(chapter_index, manual)
        print(f"Revised {chapter.title} v{chapter.version}")

    def do_finalize(self, line: str) -> None:
        """finalize <n> -- mark chapter n finalized."""
        chapter = self.engine.finalize_chapter(int(line.strip()))
        print(f"Finalized {chapter.title}")

    def do_foreshadowing(self, line: str) -> None:
        """foreshadowing list|add ... -- manage foreshadowing."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        parts = shlex.split(line)
        if not parts or parts[0] == "list":
            pending = self.engine.longform_manager.foreshadowing_tracker.get_pending(story)
            items = pending if pending else story.memory.foreshadowings
            if not items:
                print("No foreshadowing recorded.")
                return
            for item in items:
                target = f" -> target chapter {item.target_chapter}" if item.target_chapter else ""
                print(f"{item.id} [{item.status}] ch{item.created_chapter}{target}: {item.description}")
            return
        if parts[0] == "add":
            if len(parts) < 3:
                print('Usage: /foreshadowing add <created_chapter> "<description>" [target_chapter]')
                return
            created_chapter = int(parts[1])
            description = parts[2]
            target = int(parts[3]) if len(parts) > 3 else None
            item = self.engine.longform_manager.add_foreshadowing(story, description, created_chapter, target)
            story.touch()
            self.engine.save_state()
            print(f"Added {item.id}: {item.description}")
            return
        print("Usage: /foreshadowing list | /foreshadowing add <chapter> \"description\" [target]")

    def do_causality(self, line: str) -> None:
        """causality show [event_id] -- show causal events or a related chain."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        parts = shlex.split(line)
        event_id = parts[1] if len(parts) >= 2 and parts[0] == "show" else None
        if event_id:
            chain = self.engine.longform_manager.causality_tracker.get_related_chain(story, event_id)
            print(chain)
            return
        if not story.memory.causal_events:
            print("No causal events recorded.")
            return
        for event in story.memory.causal_events:
            print(f"{event.id} ch{event.chapter}: {event.description}")

    def do_pacing(self, line: str) -> None:
        """pacing check -- check recent pacing trend."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        history = self.engine.longform_manager.pacing_history.get(str(story.id), [])
        if not history and story.content.chapters:
            for chapter in story.content.chapters.values():
                if chapter.content:
                    analysis = self.engine.longform_manager.pacing_analyzer.analyze_chapter(chapter.content)
                    history.append({"chapter": chapter.index, **analysis})
        warning = self.engine.longform_manager.pacing_analyzer.check_pacing_trend(history)
        print(warning)
        for item in history[-5:]:
            print(
                f"ch{item['chapter']}: conflict={item['conflict_intensity']} "
                f"dialogue={item['dialogue_ratio']} progress={item['plot_progress']}"
            )

    def do_state(self, line: str) -> None:
        """state <character_id_or_name> -- show latest character state."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        query = line.strip()
        if not query:
            print("Usage: /state <character_id_or_name>")
            return
        character_id = query
        for cid, character in story.content.characters.items():
            if query in {cid, character.name}:
                character_id = cid
                break
        state = self.engine.longform_manager.character_state_tracker.get_current_state(story, character_id)
        if state is None:
            print(f"No state recorded for {query}.")
            return
        print(state.model_dump_json(indent=2))

    def do_summary(self, line: str) -> None:
        """summary update|show -- update or show hierarchical summaries."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        command = line.strip() or "show"
        if command == "update":
            for chapter in story.content.chapters.values():
                if chapter.content:
                    self.engine.longform_manager.summary_manager.generate_chapter_summary(story, chapter.index, chapter.content)
            if story.memory.chapter_summaries:
                max_chapter = max(story.memory.chapter_summaries)
                volume_count = (max_chapter - 1) // self.engine.longform_manager.summary_manager.chapters_per_volume + 1
                for volume in range(1, volume_count + 1):
                    self.engine.longform_manager.summary_manager.generate_volume_summary(story, volume)
            story.touch()
            self.engine.save_state()
            print("Summaries updated.")
        if not story.memory.chapter_summaries:
            print("No summaries recorded.")
            return
        for index in sorted(story.memory.chapter_summaries):
            summary = story.memory.chapter_summaries[index]
            print(f"第{index}章: {summary.chapter_summary}")
        for volume in story.memory.volume_summaries:
            print(f"卷{volume.volume} {volume.chapter_range}: {volume.summary}")

    def do_dashboard(self, line: str) -> None:
        """dashboard -- show a story panorama summary."""
        story = self.engine.story
        if story is None:
            print("No active story. Use /load <story_id> or /new_story first.")
            return
        data = DashboardDataProvider(story).get_all_data()
        overview = data.story_overview
        pending = [item for item in data.foreshadowings if item["status"] == "pending"]
        overdue = [item for item in data.foreshadowings if item["status"] == "overdue"]
        fulfilled = [item for item in data.foreshadowings if item["status"] == "fulfilled"]
        latest_pacing = data.pacing_heatmap[-1] if data.pacing_heatmap else None

        bold = "\033[1m"
        cyan = "\033[36m"
        yellow = "\033[33m"
        red = "\033[31m"
        green = "\033[32m"
        reset = "\033[0m"

        print(f"\n{bold}{overview['title']}{reset} | {overview['genre']} | chapter {overview['current_chapter']}/{overview['total_chapters']}")
        print(f"{overview['premise']}\n")
        print(
            f"{cyan}Overview{reset}: drafts={overview['drafted_chapters']} "
            f"finalized={overview['completed_chapters']} characters={overview['character_count']} "
            f"events={overview['event_count']}"
        )
        print(
            f"{cyan}Foreshadowing{reset}: {green}{len(fulfilled)} fulfilled{reset} | "
            f"{yellow}{len(pending)} pending{reset} | {red}{len(overdue)} overdue{reset}"
        )
        for item in overdue[:5]:
            print(
                f"  {red}overdue{reset} {item['id']}: {item['description'][:70]} "
                f"(created ch{item['created_chapter']}, target ch{item['target_chapter']})"
            )

        print(f"\n{cyan}Character states{reset}:")
        if not data.character_timeline:
            print("  no character state data")
        for name, timeline in data.character_timeline.items():
            if timeline:
                latest = timeline[-1]
                print(f"  {name}: {latest['emotion'] or 'unknown'} @ {latest['location'] or 'unknown'}")

        if latest_pacing:
            print(
                f"\n{cyan}Latest pacing{reset}: conflict={latest_pacing['conflict_intensity']}/10 "
                f"dialogue={latest_pacing['dialogue_ratio']}% action={latest_pacing['action_ratio']}%"
            )
        print(f"\nDashboard URL: http://127.0.0.1:8000/dashboard/?story_id={overview['id']}")

    def do_auto_write(self, line: str) -> None:
        """auto-write <n> -- write, review, revise, and re-review chapter n."""
        text = line.strip()
        if not text:
            print("Usage: /auto-write <chapter>")
            return
        chapter_index = int(text)
        print(f"Starting autonomous revision loop for chapter {chapter_index}...")
        result = self.engine.auto_write_chapter(chapter_index)
        self._print_auto_report(result)

    def do_agent(self, line: str) -> None:
        """agent <natural language task> -- let the director choose and run tools."""
        message = line.strip()
        if not message:
            print("Usage: /agent <自然语言任务>")
            return
        run = self.engine.run_director_agent(message)
        print(f"Director run {run.id} [{run.status}]")
        for step in run.steps:
            print(f"Step {step.step}: {step.selected_tool}")
            print(f"Reason: {step.reasoning_summary}")
            if step.tool_args:
                print(f"Args: {step.tool_args}")
            print(f"Observation: {step.observation or step.error}")
        if run.final_summary:
            print(f"Final Summary: {run.final_summary}")

    def do_batch_write(self, line: str) -> None:
        """batch-write <start> <end> [draft] -- generate many chapters in one run."""
        parts = shlex.split(line)
        if len(parts) < 2:
            print("Usage: /batch-write <start> <end> [draft]")
            return
        start = int(parts[0])
        end = int(parts[1])
        use_auto = not (len(parts) > 2 and parts[2].lower() == "draft")
        print(f"Batch writing chapters {start}-{end} ({'auto-revision' if use_auto else 'draft only'})...")
        report = self.engine.batch_write_chapters(start, end, use_auto)
        print(f"Completed {report.completed}, failed {report.failed}")
        for item in report.results:
            score = f" score={item.auto_revision_score:.2f}" if item.auto_revision_score is not None else ""
            print(f"  ch{item.chapter_index}: {item.status}{score} {item.title} ({item.word_count} chars)")

    def do_auto_status(self, line: str) -> None:
        """auto-status -- show autonomous revision status."""
        status = self.engine.get_auto_status()
        print(status)

    def do_auto_stop(self, line: str) -> None:
        """auto-stop -- request the active autonomous revision loop to stop."""
        if self.engine.stop_auto_revision():
            print("Stop requested.")
        else:
            print("No active auto-revision loop.")

    def do_report(self, line: str) -> None:
        """report <chapter> -- show auto-revision test report."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        text = line.strip()
        if not text:
            print("Usage: /report <chapter>")
            return
        parts = shlex.split(text)
        chapter_index = int(parts[0])
        export = len(parts) > 1 and parts[1] == "export"
        report = story.quality.auto_revision_reports.get(chapter_index)
        if report is None:
            print(f"No auto-revision report for chapter {chapter_index}.")
            return
        if export:
            path = self.engine.export_auto_revision_report(chapter_index)
            print(f"Exported report to {path}")
            return
        self._print_auto_report(report)

    def _print_auto_report(self, result) -> None:
        """以彩色终端格式打印自动修订报告，包括状态、各轮分数、问题详情和残留问题。"""
        bold = "\033[1m"
        green = "\033[32m"
        red = "\033[31m"
        cyan = "\033[36m"
        yellow = "\033[33m"
        reset = "\033[0m"
        status = f"{green}PASSED{reset}" if result.passed else f"{red}NOT PASSED{reset}"
        if result.stopped:
            status = f"{yellow}STOPPED{reset}"
        print(f"\n{bold}Auto-Revision Report: Chapter {result.chapter_index}{reset}")
        print(f"Status: {status} | Final score: {result.final_score:.2f}")
        print(f"{cyan}Rounds{reset}:")
        for round_report in result.rounds:
            scores = round_report.review_report.scores
            print(
                f"  Round {round_report.round}: total={round_report.total_score:.2f} "
                f"logic={scores.logic_consistency:.1f} char={scores.character_fidelity:.1f} "
                f"foreshadow={scores.foreshadowing_handling:.1f} pacing={scores.pacing:.1f} "
                f"style={scores.style_uniformity:.1f}"
            )
            if round_report.modification_summary:
                print(f"    fix: {round_report.modification_summary}")
            for issue in round_report.review_report.issues[:5]:
                print(f"    - [{issue.severity}] {issue.dimension}: {issue.description}")
        if result.residual_issues:
            print(f"{red}Residual issues{reset}:")
            for issue in result.residual_issues:
                print(f"  - [{issue.severity}] {issue.dimension}: {issue.description}")
        else:
            print(f"{green}No residual issues recorded.{reset}")

    def do_show(self, line: str) -> None:
        """show <n> -- show chapter content."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        chapter = story.content.chapters[int(line.strip())]
        print(f"# {chapter.title} (v{chapter.version}, {chapter.status})\n")
        print(chapter.content)

    def do_status(self, line: str) -> None:
        """status -- show current story status."""
        story = self.engine.story
        if story is None:
            print("No active story.")
            return
        print(f"{story.title} | {story.status} | current chapter: {story.current_chapter}")
        print(f"id: {story.id}")

    def do_config(self, line: str) -> None:
        """config -- show loaded configuration."""
        print(self.engine.config.model_dump_json(indent=2))

    def do_export(self, line: str) -> None:
        """export [markdown] -- export story to Markdown."""
        fmt = (line.strip() or "markdown").lower()
        if fmt not in {"markdown", "md"}:
            print("Only Markdown export is implemented in this version.")
            return
        path = self.engine.export_markdown()
        print(f"Exported to {path}")

    def do_exit(self, line: str) -> bool:
        """exit -- quit NovelForge."""
        return True

    do_quit = do_exit


def main() -> int:
    """启动 NovelForge 命令行交互界面。如果传入 --help 则打印帮助信息，否则进入 cmdloop。"""
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "NovelForge CLI\n\n"
            "Usage:\n"
            "  python -m novelforge\n\n"
            "Commands:\n"
            "  /new_story <premise>\n"
            "  /outline [num_chapters]\n"
            "  /stories\n"
            "  /beats <n>\n"
            "  /write <n>\n"
            "  /review <n>\n"
            "  /revise <n> [manual revised content]\n"
            "  /foreshadowing list|add <chapter> \"description\" [target]\n"
            "  /causality show [event_id]\n"
            "  /pacing check\n"
            "  /state <character_id_or_name>\n"
            "  /summary update|show\n"
            "  /dashboard\n"
            "  /agent <natural language task>\n"
            "  /auto-write <n>\n"
            "  /batch-write <start> <end> [draft]\n"
            "  /auto-status\n"
            "  /auto-stop\n"
            "  /report <n> [export]\n"
            "  /show <n>\n"
            "  /status\n"
            "  /export markdown\n"
            "  /exit"
        )
        return 0
    NovelForgeShell().cmdloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
