"""Fail-closed exact-window macOS backend behavior without posting native input."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.backends.macos import MacOSComputerControlBackend
from sim_pilot.computer_control.errors import StaleDesktopFrameError
from sim_pilot.computer_control.models import (
    DesktopWindowIdentity,
    InputGesture,
    InputGestureKind,
    KeyModifier,
    ScreenPoint,
    WindowBounds,
)


def _record_click(sent: list[tuple[int, int]]) -> Callable[[int, int], None]:
    def record(x: int, y: int) -> None:
        sent.append((x, y))

    return record


def _record_key(
    sent: list[tuple[int, tuple[KeyModifier, ...]]],
) -> Callable[[int, tuple[KeyModifier, ...]], None]:
    def record(code: int, modifiers: tuple[KeyModifier, ...]) -> None:
        sent.append((code, modifiers))

    return record


def _return_capture(
    captured: CapturedDesktopFrame,
) -> Callable[..., CapturedDesktopFrame]:
    def capture(*, process_id: int) -> CapturedDesktopFrame:
        del process_id
        return captured

    return capture


def _window(*, frontmost: bool = True, x: int = 10) -> DesktopWindowIdentity:
    return DesktopWindowIdentity(
        process_id=77,
        window_id="42",
        title="Software Inc",
        bounds=WindowBounds(x=x, y=20, width=100, height=50),
        display_scale=2.0,
        frontmost=frontmost,
    )


def _capture_backend(monkeypatch: pytest.MonkeyPatch) -> MacOSComputerControlBackend:
    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert "-R10,20,100,50" in arguments
        Image.new("RGB", (200, 100), (20, 30, 40)).save(Path(arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.subprocess.run", run)
    return MacOSComputerControlBackend(
        "Software Inc", activator=lambda: None, window_resolver=lambda _pid: _window()
    )


def test_identical_pixels_have_unique_capture_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _capture_backend(monkeypatch)
    first = backend.capture(process_id=77).metadata
    second = backend.capture(process_id=77).metadata
    assert first.sha256 == second.sha256
    assert first.frame_id != second.frame_id
    assert (first.capture_sequence, second.capture_sequence) == (1, 2)


def test_capture_normalizes_window_before_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    def normalize(_pid: int) -> None:
        events.append("normalize")

    def resolve(_pid: int) -> DesktopWindowIdentity:
        events.append("resolve")
        return _window()

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Image.new("RGB", (200, 100), (20, 30, 40)).save(Path(arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.subprocess.run", run)
    backend = MacOSComputerControlBackend(
        "Software Inc",
        activator=lambda: events.append("activate"),
        window_resolver=resolve,
        window_normalizer=normalize,
    )

    backend.capture(process_id=77)

    assert events[:3] == ["activate", "normalize", "resolve"]


def test_capture_waits_for_full_screen_window_to_become_frontmost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = iter((_window(frontmost=False), _window(), _window()))

    def resolve(_pid: int) -> DesktopWindowIdentity:
        return next(identities)

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Image.new("RGB", (200, 100), (20, 30, 40)).save(Path(arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.subprocess.run", run)
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.time.sleep", no_sleep)
    backend = MacOSComputerControlBackend(
        "Software Inc",
        activator=lambda: None,
        window_resolver=resolve,
    )

    frame = backend.capture(process_id=77).metadata

    assert frame.window_frontmost


def test_capture_reactivates_when_full_screen_focus_does_not_stick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activations = 0

    def activate() -> None:
        nonlocal activations
        activations += 1

    def resolve(_pid: int) -> DesktopWindowIdentity:
        return _window(frontmost=activations >= 2)

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Image.new("RGB", (200, 100), (20, 30, 40)).save(Path(arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.subprocess.run", run)
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._FRONTMOST_SETTLE_SECONDS", 0.0)
    backend = MacOSComputerControlBackend(
        "Software Inc",
        activator=activate,
        window_resolver=resolve,
    )

    frame = backend.capture(process_id=77).metadata

    assert activations == 2
    assert frame.window_frontmost


def test_execute_revalidates_window_and_dispatches_one_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata
    sent: list[tuple[int, int]] = []

    def post_click(x: int, y: int) -> None:
        sent.append((x, y))

    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        post_click,
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="manage_teams_button",
        intended_effect="open Manage Teams",
    )
    backend.execute(gesture, frame=frame)
    assert sent == [(50, 40)]


def test_execute_waits_for_full_screen_window_before_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata
    identities = iter((_window(frontmost=False), _window()))
    backend._window_resolver = lambda _pid: next(identities)  # type: ignore[reportPrivateUsage]
    sent: list[tuple[int, int]] = []

    def no_sleep(_seconds: float) -> None:
        return None

    def post_click(x: int, y: int) -> None:
        sent.append((x, y))

    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.time.sleep", no_sleep)
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        post_click,
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="safe_target",
        intended_effect="test full-screen activation",
    )

    backend.execute(gesture, frame=frame)

    assert sent == [(50, 40)]


def test_execute_rejects_stale_or_changed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata
    gesture = InputGesture(
        kind=InputGestureKind.KEY,
        key_code=49,
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="time_control",
        intended_effect="resume",
        created_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    with pytest.raises(StaleDesktopFrameError, match="stale"):
        backend.execute(gesture, frame=frame)

    fresh = gesture.model_copy(update={"created_at": datetime.now(UTC)})
    backend._window_resolver = lambda _pid: _window(x=11)  # type: ignore[reportPrivateUsage]
    with pytest.raises(StaleDesktopFrameError, match="window identity changed"):
        backend.execute(fresh, frame=frame)


def test_execute_revalidates_aged_identical_frame_before_one_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=3)}
    )
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        _record_click(sent),
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="safe_target",
        intended_effect="click after exact pixel revalidation",
    )

    backend.execute(gesture, frame=frame)

    assert sent == [(50, 40)]


def test_execute_allows_bounded_caret_blink_for_aged_focused_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=3)}
    )
    changed_image = Image.new("RGB", (200, 100), (20, 30, 40))
    for x in range(98, 100):
        for y in range(40, 50):
            changed_image.putpixel((x, y), (230, 230, 230))
    changed = CapturedDesktopFrame(
        frame.model_copy(
            update={
                "frame_id": "e" * 64,
                "capture_sequence": 2,
                "captured_at": datetime.now(UTC),
                "sha256": "f" * 64,
            }
        ),
        changed_image,
    )
    sent: list[tuple[int, tuple[KeyModifier, ...]]] = []
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(backend, "capture", _return_capture(changed))
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_key",
        _record_key(sent),
    )
    gesture = InputGesture(
        kind=InputGestureKind.KEY,
        key_code=0,
        modifiers=(KeyModifier.COMMAND,),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="product_configuration",
        target_id="product_name_input",
        intended_effect="select focused product name",
    )

    backend.execute(gesture, frame=frame)

    assert sent == [(0, (KeyModifier.COMMAND,))]


def test_execute_rejects_aged_frame_when_exact_pixels_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=3)}
    )
    changed = CapturedDesktopFrame(
        frame.model_copy(
            update={
                "frame_id": "c" * 64,
                "capture_sequence": 2,
                "captured_at": datetime.now(UTC),
                "sha256": "d" * 64,
            }
        ),
        Image.new("RGB", (200, 100), (40, 30, 20)),
    )
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(backend, "capture", _return_capture(changed))
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        _record_click(sent),
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="safe_target",
        intended_effect="reject changed pixels",
    )

    with pytest.raises(StaleDesktopFrameError, match="pixels changed"):
        backend.execute(gesture, frame=frame)

    assert sent == []


def test_execute_allows_bounded_background_change_outside_exact_target_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=3)}
    )
    fresh_image = Image.new("RGB", (200, 100), (20, 30, 40))
    fresh_image.putpixel((5, 5), (40, 30, 40))
    changed = CapturedDesktopFrame(
        frame.model_copy(
            update={
                "frame_id": "c" * 64,
                "capture_sequence": 2,
                "captured_at": datetime.now(UTC),
                "sha256": "d" * 64,
            }
        ),
        fresh_image,
    )
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(backend, "capture", _return_capture(changed))
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        _record_click(sent),
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="safe_target",
        intended_effect="allow bounded animation away from the exact target",
    )

    backend.execute(gesture, frame=frame)

    assert sent == [(50, 40)]


def test_execute_allows_bounded_animation_inside_stable_target_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=3)}
    )
    fresh_image = Image.new("RGB", (200, 100), (20, 30, 40))
    fresh_image.putpixel((80, 40), (25, 35, 45))
    changed = CapturedDesktopFrame(
        frame.model_copy(
            update={
                "frame_id": "c" * 64,
                "capture_sequence": 2,
                "captured_at": datetime.now(UTC),
                "sha256": "d" * 64,
            }
        ),
        fresh_image,
    )
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr(backend, "capture", _return_capture(changed))
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._post_click",
        _record_click(sent),
    )
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=50, y=40),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="safe_target",
        intended_effect="allow subtle target animation",
    )

    backend.execute(gesture, frame=frame)

    assert sent == [(50, 40)]


def test_execute_rejects_frame_too_old_for_exact_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata.model_copy(
        update={"captured_at": datetime.now(UTC) - timedelta(seconds=11)}
    )
    gesture = InputGesture(
        kind=InputGestureKind.KEY,
        key_code=49,
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="time_control",
        intended_effect="reject an excessively old target",
    )
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )

    with pytest.raises(StaleDesktopFrameError, match="too old"):
        backend.execute(gesture, frame=frame)


def test_key_text_and_scroll_dispatch_exact_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    sent: list[object] = []

    def post_key(code: int, modifiers: tuple[KeyModifier, ...]) -> None:
        sent.append((code, modifiers))

    def post_text(value: str) -> None:
        sent.append(value)

    def post_scroll(x: int, y: int, delta_x: int, delta_y: int) -> None:
        sent.append((x, y, delta_x, delta_y))

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._post_key", post_key)
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._post_text", post_text)
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._post_scroll", post_scroll)
    shared = {
        "expected_process_id": 77,
        "expected_window_id": "42",
        "expected_window_bounds": frame.window_bounds,
        "expected_frame_id": frame.frame_id,
        "expected_scene": "manage_teams",
        "target_id": "safe_control",
    }
    backend.execute(
        InputGesture(
            kind=InputGestureKind.KEY,
            key_code=0,
            modifiers=(KeyModifier.COMMAND,),
            intended_effect="select all filter text",
            **shared,  # type: ignore[arg-type]
        ),
        frame=frame,
    )
    backend.execute(
        InputGesture(
            kind=InputGestureKind.TEXT,
            text="Core",
            intended_effect="filter teams",
            **shared,  # type: ignore[arg-type]
        ),
        frame=frame,
    )
    backend.execute(
        InputGesture(
            kind=InputGestureKind.SCROLL,
            point=ScreenPoint(x=50, y=40),
            scroll_delta_x=0,
            scroll_delta_y=-4,
            intended_effect="scroll team list",
            **shared,  # type: ignore[arg-type]
        ),
        frame=frame,
    )
    assert sent == [(0, (KeyModifier.COMMAND,)), "Core", (50, 40, 0, -4)]


def test_right_click_and_pointer_move_dispatch_exact_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _capture_backend(monkeypatch)
    frame = backend.capture(process_id=77).metadata
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    sent: list[tuple[str, int, int]] = []

    def post_click(x: int, y: int, *, right: bool = False) -> None:
        sent.append(("right" if right else "left", x, y))

    def move_pointer(_graphics: object, _foundation: object, point: object) -> None:
        sent.append(("move", round(point.x), round(point.y)))  # type: ignore[attr-defined]

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._post_click", post_click)
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos._core_graphics_events",
        lambda: (object(), object()),
    )
    monkeypatch.setattr("sim_pilot.computer_control.backends.macos._move_pointer", move_pointer)
    shared = {
        "point": ScreenPoint(x=50, y=40),
        "expected_process_id": 77,
        "expected_window_id": "42",
        "expected_window_bounds": frame.window_bounds,
        "expected_frame_id": frame.frame_id,
        "expected_scene": "gameplay_paused",
        "target_id": "room-point",
    }
    backend.execute(
        InputGesture(
            kind=InputGestureKind.RIGHT_CLICK,
            intended_effect="open room context",
            **shared,  # type: ignore[arg-type]
        ),
        frame=frame,
    )
    backend.execute(
        InputGesture(
            kind=InputGestureKind.MOVE,
            intended_effect="preview placement",
            **shared,  # type: ignore[arg-type]
        ),
        frame=frame,
    )

    assert sent == [("right", 50, 40), ("move", 50, 40)]


def test_execute_rejects_point_in_spanning_display_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sim_pilot.computer_control.errors import UnsafeInputTargetError

    window = _window().model_copy(
        update={
            "bounds": WindowBounds(x=-100, y=20, width=200, height=100),
            "content_bounds": WindowBounds(x=-100, y=20, width=200, height=100),
            "visible_regions": (
                WindowBounds(x=-100, y=20, width=80, height=100),
                WindowBounds(x=20, y=20, width=80, height=100),
            ),
        }
    )

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Image.new("RGB", (400, 200), (20, 30, 40)).save(Path(arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("sim_pilot.computer_control.backends.macos.subprocess.run", run)
    monkeypatch.setattr(
        "sim_pilot.computer_control.backends.macos.accessibility_trusted", lambda: True
    )
    backend = MacOSComputerControlBackend(
        "Software Inc", activator=lambda: None, window_resolver=lambda _pid: window
    )
    frame = backend.capture(process_id=77).metadata
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=ScreenPoint(x=0, y=50),
        expected_process_id=77,
        expected_window_id="42",
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene="gameplay_paused",
        target_id="gap",
        intended_effect="reject an invisible gap",
    )

    with pytest.raises(UnsafeInputTargetError, match="visible game regions"):
        backend.execute(gesture, frame=frame)
