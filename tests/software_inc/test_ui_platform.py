"""Exact CoreGraphics Software Inc. window selection."""

import json
import subprocess
from typing import Any

import pytest

from sim_pilot.computer_control.errors import ComputerControlError
from sim_pilot.computer_control.models import DesktopWindowIdentity, WindowBounds
from sim_pilot.software_inc.ui.platform import (
    DisplayGeometry,
    _screen_backing_scales,  # pyright: ignore[reportPrivateUsage]
    normalize_software_inc_window,
    software_inc_window_identity,
)


def _window(number: int = 42, *, width: int = 1512) -> dict[str, object]:
    return {
        "kCGWindowOwnerPID": 77,
        "kCGWindowOwnerName": "Software Inc",
        "kCGWindowNumber": number,
        "kCGWindowLayer": 0,
        "kCGWindowAlpha": 1.0,
        "kCGWindowName": "Software Inc",
        "kCGWindowIsOnscreen": True,
        "kCGWindowBounds": {"X": 0, "Y": 33, "Width": width, "Height": 949},
    }


def _completed(payload: str):
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(["osascript"], 0, payload, "")

    return run


def _report(*windows: dict[str, object]) -> str:
    return json.dumps(
        {
            "frontmost_pid": 77,
            "windows": windows,
        }
    )


def test_appkit_backing_scale_is_used_for_retina_displays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed('[{"display_id":"1","backing_scale":2}]'),
    )

    assert _screen_backing_scales() == {"1": 2.0}


@pytest.fixture(autouse=True)
def active_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform._active_displays",
        lambda: (
            DisplayGeometry(
                display_id="1",
                bounds=WindowBounds(x=0, y=0, width=1512, height=982),
                capture_scale=2.0,
            ),
        ),
    )


def test_exact_window_is_bound_to_pid_title_and_frontmost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _report(_window())
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed(payload),
    )
    result = software_inc_window_identity(77)
    assert result.window_id == "42"
    assert result.frontmost
    assert result.bounds.width == 1512
    assert result.content_bounds == WindowBounds(x=0, y=33, width=1512, height=949)
    assert result.visible_regions == (result.bounds,)
    assert result.display_ids == ("1",)


def test_equal_plausible_windows_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _report(_window(), _window(43))
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed(payload),
    )
    with pytest.raises(ComputerControlError, match="ambiguous"):
        software_inc_window_identity(77)


def test_window_bounds_are_clipped_to_the_visible_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = _window()
    oversized["kCGWindowBounds"] = {"X": 0, "Y": 30, "Width": 1512, "Height": 1100}
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed(_report(oversized)),
    )

    result = software_inc_window_identity(77)

    assert result.bounds.height == 952
    assert result.content_bounds == WindowBounds(x=0, y=30, width=1512, height=1100)


def test_negative_spanning_window_uses_all_visible_display_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spanning = _window()
    spanning["kCGWindowBounds"] = {"X": -1460, "Y": 80, "Width": 1920, "Height": 1050}
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform._active_displays",
        lambda: (
            DisplayGeometry(
                display_id="built-in",
                bounds=WindowBounds(x=-1512, y=0, width=1512, height=982),
                capture_scale=1.0,
            ),
            DisplayGeometry(
                display_id="main",
                bounds=WindowBounds(x=0, y=0, width=1920, height=1080),
                capture_scale=1.0,
            ),
        ),
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed(_report(spanning)),
    )

    result = software_inc_window_identity(77)

    assert result.bounds == WindowBounds(x=-1460, y=80, width=1920, height=1000)
    assert result.content_bounds == WindowBounds(x=-1460, y=80, width=1920, height=1050)
    assert result.visible_regions == (
        WindowBounds(x=-1460, y=80, width=1460, height=902),
        WindowBounds(x=0, y=80, width=460, height=1000),
    )
    assert result.display_ids == ("built-in", "main")


def test_spanning_mixed_scale_displays_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    spanning = _window()
    spanning["kCGWindowBounds"] = {"X": -100, "Y": 30, "Width": 1512, "Height": 949}
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform._active_displays",
        lambda: (
            DisplayGeometry(
                display_id="retina",
                bounds=WindowBounds(x=-1512, y=0, width=1512, height=982),
                capture_scale=2.0,
            ),
            DisplayGeometry(
                display_id="main",
                bounds=WindowBounds(x=0, y=0, width=1512, height=982),
                capture_scale=1.0,
            ),
        ),
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.subprocess.run",
        _completed(_report(spanning)),
    )

    with pytest.raises(ComputerControlError, match="incompatible capture scales"):
        software_inc_window_identity(77)


def test_window_normalization_moves_once_and_verifies_primary_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = DisplayGeometry(
        display_id="main",
        bounds=WindowBounds(x=0, y=0, width=1920, height=1080),
        capture_scale=1.0,
    )
    before = DesktopWindowIdentity(
        process_id=77,
        window_id="42",
        title="Software Inc",
        bounds=WindowBounds(x=-1460, y=80, width=1920, height=1000),
        content_bounds=WindowBounds(x=-1460, y=80, width=1920, height=1050),
        visible_regions=(WindowBounds(x=-1460, y=80, width=1460, height=902),),
        display_ids=("built-in",),
        display_scale=1.0,
        frontmost=True,
    )
    after = before.model_copy(
        update={
            "bounds": WindowBounds(x=0, y=15, width=1920, height=1050),
            "content_bounds": WindowBounds(x=0, y=15, width=1920, height=1050),
            "visible_regions": (WindowBounds(x=0, y=15, width=1920, height=1050),),
            "display_ids": ("main",),
        }
    )
    identities = iter((before, after))

    def resolve(_pid: int) -> DesktopWindowIdentity:
        return next(identities)

    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.software_inc_window_identity",
        resolve,
    )
    monkeypatch.setattr("sim_pilot.software_inc.ui.platform._primary_display", lambda: primary)
    calls: list[list[str]] = []

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("sim_pilot.software_inc.ui.platform.subprocess.run", run)

    normalize_software_inc_window(77)

    assert len(calls) == 1
    assert calls[0][-3:] == ["77", "0", "15"]


def test_window_normalization_is_noop_when_already_on_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = DisplayGeometry(
        display_id="main",
        bounds=WindowBounds(x=0, y=0, width=1920, height=1080),
        capture_scale=1.0,
    )
    current = DesktopWindowIdentity(
        process_id=77,
        window_id="42",
        title="Software Inc",
        bounds=WindowBounds(x=0, y=15, width=1920, height=1050),
        content_bounds=WindowBounds(x=0, y=15, width=1920, height=1050),
        visible_regions=(WindowBounds(x=0, y=15, width=1920, height=1050),),
        display_ids=("main",),
        display_scale=1.0,
        frontmost=True,
    )

    def resolve(_pid: int) -> DesktopWindowIdentity:
        return current

    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.software_inc_window_identity",
        resolve,
    )
    monkeypatch.setattr("sim_pilot.software_inc.ui.platform._primary_display", lambda: primary)
    called = False

    def run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(["osascript"], 0, "", "")

    monkeypatch.setattr("sim_pilot.software_inc.ui.platform.subprocess.run", run)

    normalize_software_inc_window(77)

    assert not called


def test_window_normalization_rejects_window_larger_than_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = DisplayGeometry(
        display_id="main",
        bounds=WindowBounds(x=0, y=0, width=1280, height=720),
        capture_scale=1.0,
    )
    current = DesktopWindowIdentity(
        process_id=77,
        window_id="42",
        title="Software Inc",
        bounds=WindowBounds(x=-100, y=0, width=1380, height=720),
        content_bounds=WindowBounds(x=-100, y=0, width=1920, height=1080),
        display_scale=1.0,
        frontmost=True,
    )

    def resolve(_pid: int) -> DesktopWindowIdentity:
        return current

    monkeypatch.setattr(
        "sim_pilot.software_inc.ui.platform.software_inc_window_identity",
        resolve,
    )
    monkeypatch.setattr("sim_pilot.software_inc.ui.platform._primary_display", lambda: primary)

    with pytest.raises(ComputerControlError, match="larger than the primary display"):
        normalize_software_inc_window(77)
