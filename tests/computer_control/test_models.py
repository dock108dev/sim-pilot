"""Game-neutral desktop safety contracts."""

import pytest
from pydantic import ValidationError

from sim_pilot.computer_control.models import (
    InputGesture,
    InputGestureKind,
    ScreenPoint,
    WindowBounds,
)


def test_window_bounds_reject_outside_points() -> None:
    bounds = WindowBounds(x=10, y=20, width=100, height=50)
    assert bounds.contains(ScreenPoint(x=10, y=20))
    assert not bounds.contains(ScreenPoint(x=110, y=20))


def test_gesture_payload_is_exact() -> None:
    with pytest.raises(ValidationError, match="click requires"):
        InputGesture(
            kind=InputGestureKind.CLICK,
            expected_process_id=1,
            expected_frame_id="a" * 64,
        )
