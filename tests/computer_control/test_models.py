"""Game-neutral desktop safety contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sim_pilot.computer_control.models import (
    DesktopFrame,
    InputGesture,
    InputGestureKind,
    KeyModifier,
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
            expected_window_id="window",
            expected_window_bounds=WindowBounds(x=0, y=0, width=100, height=100),
            expected_frame_id="a" * 64,
            expected_scene="gameplay",
            target_id="pause",
            intended_effect="pause",
            created_at=datetime.now(UTC),
        )


def _gesture(**changes: object) -> InputGesture:
    values: dict[str, object] = {
        "kind": InputGestureKind.KEY,
        "key_code": 49,
        "expected_process_id": 1,
        "expected_window_id": "window",
        "expected_window_bounds": WindowBounds(x=0, y=0, width=100, height=100),
        "expected_frame_id": "a" * 64,
        "expected_scene": "gameplay_paused",
        "target_id": "time_control",
        "intended_effect": "resume",
        "created_at": datetime.now(UTC),
    }
    values.update(changes)
    return InputGesture.model_validate(values)


def test_text_and_scroll_payloads_are_discriminated() -> None:
    text = _gesture(kind=InputGestureKind.TEXT, key_code=None, text="Core")
    scroll = _gesture(
        kind=InputGestureKind.SCROLL,
        key_code=None,
        point=ScreenPoint(x=50, y=50),
        scroll_delta_x=0,
        scroll_delta_y=-4,
    )
    assert text.text == "Core"
    assert scroll.scroll_delta_y == -4
    with pytest.raises(ValidationError, match="non-zero"):
        _gesture(
            kind=InputGestureKind.SCROLL,
            key_code=None,
            point=ScreenPoint(x=50, y=50),
            scroll_delta_x=0,
            scroll_delta_y=0,
        )


def test_key_modifiers_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _gesture(modifiers=(KeyModifier.COMMAND, KeyModifier.COMMAND))


@pytest.mark.parametrize(
    "kind",
    [InputGestureKind.MOVE, InputGestureKind.RIGHT_CLICK],
)
def test_pointer_only_gestures_require_exactly_one_point(kind: InputGestureKind) -> None:
    gesture = InputGesture(
        kind=kind,
        point=ScreenPoint(x=100, y=200),
        expected_process_id=123,
        expected_window_id="window-1",
        expected_window_bounds=WindowBounds(x=10, y=20, width=800, height=600),
        expected_frame_id="a" * 64,
        expected_scene="furniture_placement",
        target_id="candidate",
        intended_effect="preview or open a context menu",
    )

    assert gesture.point == ScreenPoint(x=100, y=200)


def test_frame_separates_capture_and_pixel_identity() -> None:
    frame = DesktopFrame(
        frame_id="a" * 64,
        capture_sequence=2,
        captured_at=datetime.now(UTC),
        process_id=1,
        window_id="window",
        window_title="Game",
        window_bounds=WindowBounds(x=0, y=0, width=100, height=100),
        window_frontmost=True,
        pixel_width=200,
        pixel_height=200,
        display_scale=2.0,
        sha256="b" * 64,
        platform="macos",
    )
    assert frame.frame_id != frame.sha256
    assert frame.capture_sequence == 2
