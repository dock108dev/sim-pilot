"""Exact Software Inc. macOS window identity without Accessibility-window assumptions."""

from __future__ import annotations

import ctypes
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from sim_pilot.computer_control.errors import ComputerControlError
from sim_pilot.computer_control.models import DesktopWindowIdentity, WindowBounds

_EXPECTED_TITLE = "Software Inc"
_CORE_GRAPHICS = Path("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_WINDOW_SCRIPT = r"""
ObjC.import("AppKit");
ObjC.import("CoreGraphics");
const expectedPID = Number(
  $.NSProcessInfo.processInfo.environment.objectForKey("SIM_PILOT_PID").js
);
const ref = $.CGWindowListCopyWindowInfo(
  $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements,
  $.kCGNullWindowID
);
const windows = ObjC.castRefToObject(ref);
const output = [];
for (let index = 0; index < Number(windows.count); index++) {
  const item = ObjC.deepUnwrap(windows.objectAtIndex(index));
  if (Number(item.kCGWindowOwnerPID) === expectedPID) output.push(item);
}
const frontmost = Number($.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier);
JSON.stringify({
  frontmost_pid: frontmost,
  windows: output
});
""".strip()
_DISPLAY_SCALE_SCRIPT = r"""
ObjC.import("AppKit");
const output = [];
for (const screen of $.NSScreen.screens.js) {
  const description = ObjC.deepUnwrap(screen.deviceDescription);
  output.push({
    display_id: String(Number(description.NSScreenNumber)),
    backing_scale: Number(screen.backingScaleFactor)
  });
}
JSON.stringify(output);
""".strip()
_NORMALIZE_WINDOW_SCRIPT = r"""
on run argv
  set targetPID to (item 1 of argv) as integer
  set targetX to (item 2 of argv) as integer
  set targetY to (item 3 of argv) as integer
  tell application "System Events"
    set targetProcess to first application process whose unix id is targetPID
    set frontmost of targetProcess to true
    set targetWindow to first window of targetProcess whose name is "Software Inc"
    set position of targetWindow to {targetX, targetY}
  end tell
end run
""".strip()


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


@dataclass(frozen=True)
class DisplayGeometry:
    display_id: str
    bounds: WindowBounds
    capture_scale: float


class _WindowRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    kCGWindowOwnerPID: int
    kCGWindowOwnerName: str
    kCGWindowNumber: int
    kCGWindowLayer: int
    kCGWindowAlpha: float
    kCGWindowName: str = ""
    kCGWindowIsOnscreen: bool = False
    kCGWindowBounds: dict[str, int]


class _WindowReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    frontmost_pid: int
    windows: tuple[_WindowRecord, ...]


def software_inc_window_identity(process_id: int) -> DesktopWindowIdentity:
    """Resolve exactly one visible, titled, layer-zero Software Inc. game window."""
    if process_id < 1:
        raise ValueError("process_id must be positive")
    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", _WINDOW_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={"SIM_PILOT_PID": str(process_id)},
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "failed"
        raise ComputerControlError(f"exact Software Inc. window inspection failed: {detail}")
    try:
        report = _WindowReport.model_validate_json(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValidationError, json.JSONDecodeError) as error:
        raise ComputerControlError("exact Software Inc. window report was malformed") from error
    displays = _active_displays()
    if not displays:
        raise ComputerControlError("CoreGraphics reported no active displays")
    candidates: list[
        tuple[
            int,
            _WindowRecord,
            WindowBounds,
            WindowBounds,
            tuple[WindowBounds, ...],
            tuple[str, ...],
            float,
        ]
    ] = []
    for record in report.windows:
        raw = record.kCGWindowBounds
        try:
            bounds = WindowBounds(x=raw["X"], y=raw["Y"], width=raw["Width"], height=raw["Height"])
        except (KeyError, ValidationError):
            continue
        if (
            record.kCGWindowOwnerPID == process_id
            and record.kCGWindowOwnerName == _EXPECTED_TITLE
            and record.kCGWindowName == _EXPECTED_TITLE
            and record.kCGWindowLayer == 0
            and record.kCGWindowAlpha > 0.9
            and record.kCGWindowIsOnscreen
        ):
            intersections = tuple(
                (display, visible)
                for display in displays
                if (visible := _intersection(bounds, display.bounds)) is not None
            )
            if not intersections:
                continue
            scales = tuple(display.capture_scale for display, _ in intersections)
            if max(scales) - min(scales) > 0.1:
                raise ComputerControlError(
                    "Software Inc. spans displays with incompatible capture scales"
                )
            visible_regions = tuple(visible for _, visible in intersections)
            visible_area = sum(region.width * region.height for region in visible_regions)
            capture_bounds = _bounding_box(visible_regions)
            display_ids = tuple(display.display_id for display, _ in intersections)
            candidates.append(
                (
                    visible_area,
                    record,
                    capture_bounds,
                    bounds,
                    visible_regions,
                    display_ids,
                    scales[0],
                )
            )
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        raise ComputerControlError("no exact visible Software Inc. game window was found")
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise ComputerControlError("Software Inc. game window identity is ambiguous")
    _, record, bounds, content_bounds, visible_regions, display_ids, scale = candidates[0]
    return DesktopWindowIdentity(
        process_id=process_id,
        window_id=str(record.kCGWindowNumber),
        title=record.kCGWindowName,
        bounds=bounds,
        content_bounds=content_bounds,
        visible_regions=visible_regions,
        display_ids=display_ids,
        display_scale=scale,
        frontmost=report.frontmost_pid == process_id,
    )


def normalize_software_inc_window(process_id: int) -> None:
    """Move an unsafe/off-display game window onto the primary display once."""
    before = software_inc_window_identity(process_id)
    content = before.content_bounds or before.bounds
    primary = _primary_display()
    if _contains(primary.bounds, content):
        return
    if content.width > primary.bounds.width or content.height > primary.bounds.height:
        raise ComputerControlError(
            "Software Inc. window is larger than the primary display; select a fitting "
            "resolution or fullscreen mode before UI control"
        )
    target_x = primary.bounds.x + (primary.bounds.width - content.width) // 2
    target_y = primary.bounds.y + (primary.bounds.height - content.height) // 2
    completed = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            _NORMALIZE_WINDOW_SCRIPT,
            str(process_id),
            str(target_x),
            str(target_y),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "failed"
        raise ComputerControlError(
            f"could not place Software Inc. on the primary display: {detail}"
        )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        current = software_inc_window_identity(process_id)
        current_content = current.content_bounds or current.bounds
        if current.window_id == before.window_id and _contains(primary.bounds, current_content):
            return
        time.sleep(0.1)
    raise ComputerControlError(
        "Software Inc. did not settle fully inside the primary display after one move"
    )


def _active_displays() -> tuple[DisplayGeometry, ...]:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    get_displays = core_graphics.CGGetActiveDisplayList
    get_displays.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    get_displays.restype = ctypes.c_int32
    count = ctypes.c_uint32()
    if get_displays(0, None, ctypes.byref(count)) != 0 or count.value == 0:
        return ()
    identifiers = (ctypes.c_uint32 * count.value)()
    if get_displays(count.value, identifiers, ctypes.byref(count)) != 0:
        return ()
    display_bounds = core_graphics.CGDisplayBounds
    display_bounds.argtypes = [ctypes.c_uint32]
    display_bounds.restype = _CGRect
    pixel_width = core_graphics.CGDisplayPixelsWide
    pixel_width.argtypes = [ctypes.c_uint32]
    pixel_width.restype = ctypes.c_size_t
    backing_scales = _screen_backing_scales()
    result: list[DisplayGeometry] = []
    for identifier in identifiers[: count.value]:
        raw = display_bounds(identifier)
        width = round(raw.size.width)
        height = round(raw.size.height)
        if width <= 0 or height <= 0:
            continue
        bounds = WindowBounds(
            x=round(raw.origin.x),
            y=round(raw.origin.y),
            width=width,
            height=height,
        )
        display_id = str(int(identifier))
        fallback_scale = float(pixel_width(identifier)) / width
        capture_scale = backing_scales.get(display_id)
        if capture_scale is None:
            capture_scale = fallback_scale
        result.append(
            DisplayGeometry(
                display_id=display_id,
                bounds=bounds,
                capture_scale=capture_scale,
            )
        )
    return tuple(result)


def _screen_backing_scales() -> dict[str, float]:
    """Read AppKit backing scales; CGDisplayPixelsWide can be logical in HiDPI modes."""
    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", _DISPLAY_SCALE_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}
    try:
        payload = TypeAdapter(list[dict[str, object]]).validate_python(
            json.loads(completed.stdout.strip().splitlines()[-1])
        )
    except (IndexError, json.JSONDecodeError, ValidationError):
        return {}
    result: dict[str, float] = {}
    for item in payload:
        display_id = item.get("display_id")
        scale = item.get("backing_scale")
        if (
            isinstance(display_id, str)
            and display_id
            and isinstance(scale, (int, float))
            and not isinstance(scale, bool)
            and 0.5 <= float(scale) <= 4.0
        ):
            result[display_id] = float(scale)
    return result


def _primary_display() -> DisplayGeometry:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    main_display = core_graphics.CGMainDisplayID
    main_display.argtypes = []
    main_display.restype = ctypes.c_uint32
    expected = str(int(main_display()))
    for display in _active_displays():
        if display.display_id == expected:
            return display
    raise ComputerControlError("CoreGraphics primary display identity was unavailable")


def _intersection(first: WindowBounds, second: WindowBounds) -> WindowBounds | None:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    if right <= left or bottom <= top:
        return None
    return WindowBounds(x=left, y=top, width=right - left, height=bottom - top)


def _bounding_box(regions: tuple[WindowBounds, ...]) -> WindowBounds:
    left = min(region.x for region in regions)
    top = min(region.y for region in regions)
    right = max(region.x + region.width for region in regions)
    bottom = max(region.y + region.height for region in regions)
    return WindowBounds(x=left, y=top, width=right - left, height=bottom - top)


def _contains(container: WindowBounds, item: WindowBounds) -> bool:
    return (
        item.x >= container.x
        and item.y >= container.y
        and item.x + item.width <= container.x + container.width
        and item.y + item.height <= container.y + container.height
    )


__all__ = ["normalize_software_inc_window", "software_inc_window_identity"]
