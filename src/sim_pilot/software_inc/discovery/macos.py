"""Read-only macOS process, bundle, architecture, and capture probes."""

import ctypes
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image

from sim_pilot.computer_control.backends.macos import accessibility_trusted

_CORE_GRAPHICS = Path("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def bundle_info(app_path: Path) -> dict[str, object]:
    info_path = app_path / "Contents/Info.plist"
    if not info_path.is_file():
        return {}
    with info_path.open("rb") as stream:
        loaded: object = plistlib.load(stream)
    if not isinstance(loaded, dict):
        return {}
    raw = cast("dict[object, object]", loaded)
    return {key: value for key, value in raw.items() if isinstance(key, str)}


def bundle_executable(app_path: Path, info: dict[str, object]) -> Path | None:
    configured = info.get("CFBundleExecutable")
    if isinstance(configured, str) and configured.strip():
        candidate = app_path / "Contents/MacOS" / configured
        return candidate if candidate.is_file() else None
    directory = app_path / "Contents/MacOS"
    candidates = sorted(path for path in directory.glob("*") if path.is_file())
    return candidates[0] if len(candidates) == 1 else None


def unity_version(info: dict[str, object]) -> str | None:
    text = str(info.get("CFBundleGetInfoString", ""))
    match = re.search(r"Unity Player version ([^ ]+)", text)
    return match.group(1) if match else None


def architectures(path: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["lipo", "-archs", str(path)], check=False, capture_output=True, text=True
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return tuple(sorted(set(completed.stdout.split())))
    fallback = subprocess.run(
        ["file", "-b", str(path)], check=False, capture_output=True, text=True
    )
    text = fallback.stdout.lower()
    found = tuple(arch for arch in ("arm64", "x86_64") if arch in text)
    return found


def running_process(executable: Path) -> tuple[int | None, str | None, str | None]:
    completed = subprocess.run(
        ["pgrep", "-f", rf"^{re.escape(str(executable))}($|[[:space:]])"],
        check=False,
        capture_output=True,
        text=True,
    )
    identifiers = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(identifiers) != 1 or not identifiers[0].isdigit():
        return None, None, None
    process_id = int(identifiers[0])
    executable_architectures = architectures(executable)
    architecture = executable_architectures[0] if len(executable_architectures) == 1 else None
    parent_result = subprocess.run(
        ["ps", "-o", "ppid=", "-p", str(process_id)],
        check=False,
        capture_output=True,
        text=True,
    )
    parent = parent_result.stdout.strip()
    parentage: str | None = None
    if parent.isdigit():
        command_result = subprocess.run(
            ["ps", "-o", "comm=", "-p", parent],
            check=False,
            capture_output=True,
            text=True,
        )
        parentage = command_result.stdout.strip() or f"pid:{parent}"
    return process_id, architecture, parentage


def functional_screen_capture() -> bool:
    with tempfile.TemporaryDirectory(prefix="sim-pilot-software-inc-capture-") as directory:
        target = Path(directory) / "capture.png"
        completed = subprocess.run(
            ["screencapture", "-x", "-m", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0 and target.is_file() and target.stat().st_size > 0


def _main_display_scale() -> float:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    main_display = core_graphics.CGMainDisplayID
    main_display.argtypes = []
    main_display.restype = ctypes.c_uint32
    bounds = core_graphics.CGDisplayBounds
    bounds.argtypes = [ctypes.c_uint32]
    bounds.restype = _CGRect
    identifier = main_display()
    logical = bounds(identifier)
    if logical.size.width <= 0:
        return 1.0
    with tempfile.TemporaryDirectory(prefix="sim-pilot-software-inc-scale-") as directory:
        target = Path(directory) / "capture.png"
        completed = subprocess.run(
            ["screencapture", "-x", "-m", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not target.is_file():
            return 1.0
        try:
            with Image.open(target) as image:
                pixel_width = image.width
        except OSError:
            return 1.0
    scale = float(pixel_width) / logical.size.width
    return scale if 0.5 <= scale <= 4.0 else 1.0


def window_identity(
    process_id: int,
) -> tuple[str, int, int, int, int, float] | None:
    """Read the largest exact game window for the PID through macOS System Events."""
    script = f"""
set targetPID to {process_id}
tell application "System Events"
    set matches to every process whose unix id is targetPID
    if (count of matches) is not 1 then error "process identity is ambiguous"
    set gameProcess to item 1 of matches
    if (count of windows of gameProcess) is less than 1 then error "process has no window"
    set gameWindow to missing value
    set gameArea to 0
    repeat with candidateWindow in windows of gameProcess
        set candidateName to name of candidateWindow as text
        set candidateSize to size of candidateWindow
        set candidateArea to (item 1 of candidateSize) * (item 2 of candidateSize)
        if candidateName is "Software Inc" and candidateArea > gameArea then
            set gameWindow to candidateWindow
            set gameArea to candidateArea
        end if
    end repeat
    if gameWindow is missing value then error "exact game window is unavailable"
    set windowName to name of gameWindow
    set windowPosition to position of gameWindow
    set windowSize to size of gameWindow
    return (windowName as text) & (ASCII character 31) & ¬
        (item 1 of windowPosition as text) & (ASCII character 31) & ¬
        (item 2 of windowPosition as text) & (ASCII character 31) & ¬
        (item 1 of windowSize as text) & (ASCII character 31) & ¬
        (item 2 of windowSize as text)
end tell
""".strip()
    completed = subprocess.run(
        ["osascript", "-e", script], check=False, capture_output=True, text=True
    )
    fields = completed.stdout.rstrip("\n").split("\x1f")
    if completed.returncode != 0 or len(fields) != 5:
        return None
    title = fields[0].strip()
    try:
        x, y, width, height = (int(value.strip()) for value in fields[1:])
    except ValueError:
        return None
    if not title or width <= 0 or height <= 0:
        return None
    return title, x, y, width, height, _main_display_scale()


__all__ = [
    "accessibility_trusted",
    "architectures",
    "bundle_executable",
    "bundle_info",
    "functional_screen_capture",
    "running_process",
    "unity_version",
    "window_identity",
]
