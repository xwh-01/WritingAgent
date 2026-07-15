"""Small interactive shell over the same application facade as the HTTP API."""

from __future__ import annotations

import shlex

import cmd2

from novelforge.orchestrator.engine import NovelForgeEngine


class NovelForgeShell(cmd2.Cmd):
    prompt = "novelforge> "
    intro = "NovelForge ready. Type help to list commands."

    def __init__(self, engine: NovelForgeEngine | None = None) -> None:
        super().__init__()
        self.engine = engine or NovelForgeEngine()

    def do_new(self, line: str) -> None:
        """new <title> | <premise> -- create a story."""
        title, separator, premise = line.partition("|")
        if not separator or not premise.strip():
            self.perror("Usage: new <title> | <premise>")
            return
        story = self.engine.start_new_story(premise.strip(), title.strip())
        self.poutput(f"Created {story.title} ({story.id})")

    def do_load(self, line: str) -> None:
        """load <story_id> -- load a story."""
        story = self.engine.load_state(line.strip())
        self.poutput(f"Loaded {story.title} ({story.status})")

    def do_stories(self, _line: str) -> None:
        """stories -- list canonical stories."""
        for record in self.engine.repository.list_records():
            self.poutput(
                f"{record.id} | chapter {record.current_chapter} | "
                f"{record.status} | {record.title}"
            )

    def do_outline(self, line: str) -> None:
        """outline [count] -- generate or complete the outline."""
        count = int(line.strip()) if line.strip() else None
        for item in self.engine.generate_outline(count):
            self.poutput(f"{item.chapter_index}. {item.title} — {item.summary}")

    def do_beats(self, line: str) -> None:
        """beats <chapter> -- plan scenes."""
        chapter = self.engine.generate_beats(int(line.strip()))
        for beat in chapter.beats:
            self.poutput(f"{beat.scene_index}. {beat.title or beat.description}")

    def do_write(self, line: str) -> None:
        """write <chapter> -- generate, repair, validate, and commit prose."""
        chapter = self.engine.write_chapter(int(line.strip()))
        self.poutput(f"Committed {chapter.title} v{chapter.version}")

    def do_review(self, line: str) -> None:
        """review <chapter> -- persist an editorial review."""
        report = self.engine.request_review(int(line.strip()))
        self.poutput(report.model_dump_json(indent=2))

    def do_propose(self, line: str) -> None:
        """propose <chapter> <instruction> -- create a gated revision proposal."""
        parts = shlex.split(line)
        if len(parts) < 2:
            self.perror("Usage: propose <chapter> <instruction>")
            return
        proposal = self.engine.create_revision_proposal(int(parts[0]), " ".join(parts[1:]))
        self.poutput(f"{proposal.id} eligible={proposal.eligible}")

    def do_accept(self, line: str) -> None:
        """accept <proposal_id> -- commit an eligible revision."""
        chapter = self.engine.accept_revision_proposal(line.strip())
        self.poutput(f"Committed {chapter.title} v{chapter.version}")

    def do_reject(self, line: str) -> None:
        """reject <proposal_id> -- reject a proposal without changing prose."""
        proposal = self.engine.reject_revision_proposal(line.strip())
        self.poutput(f"Rejected {proposal.id}")

    def do_batch(self, line: str) -> None:
        """batch <start> <end> -- reliably write a chapter range."""
        start, end = (int(value) for value in line.split())
        report = self.engine.batch_write_chapters(start, end)
        self.poutput(report.model_dump_json(indent=2))

    def do_export(self, line: str) -> None:
        """export [path] -- export Markdown."""
        path = self.engine.export_markdown(line.strip() or None)
        self.poutput(str(path))


def main() -> int:
    shell = NovelForgeShell()
    try:
        shell.cmdloop()
    finally:
        shell.engine.close()
    return 0


__all__ = ["NovelForgeShell", "main"]
