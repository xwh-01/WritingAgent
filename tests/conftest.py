from __future__ import annotations

import pytest

from novelforge.domain import ChapterContract, ChapterOutline, Story


@pytest.fixture
def planned_story() -> Story:
    story = Story(title="Test Story", premise="A difficult choice changes a family.")
    story.design.outlines = [
        ChapterOutline(
            chapter_index=1,
            title="The Choice",
            summary="The protagonist must choose.",
            conflict="Duty conflicts with loyalty.",
            pov_character="hero",
        )
    ]
    story.design.chapter_contracts[1] = ChapterContract(
        chapter_index=1,
        must_happen=["The protagonist makes a choice."],
        must_not_happen=["The conflict is solved by coincidence."],
        ending_hook="A hidden cost is revealed.",
    )
    return story
