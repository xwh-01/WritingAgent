from __future__ import annotations

import pytest
from pydantic import ValidationError

from novelforge.domain import SceneEndState


def test_scene_end_state_normalizes_only_empty_container_swaps() -> None:
    state = SceneEndState.model_validate(
        {
            "relationship_changes": {},
            "questions_created": {},
            "location_changes": [],
            "ending_state": [],
        }
    )

    assert state.relationship_changes == []
    assert state.questions_created == []
    assert state.location_changes == {}
    assert state.ending_state == {}


def test_scene_end_state_rejects_nonempty_wrong_container_types() -> None:
    with pytest.raises(ValidationError):
        SceneEndState.model_validate({"relationship_changes": {"pair": "changed"}})
