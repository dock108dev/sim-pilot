"""Native macOS screenshot, click, and key primitives."""

import ctypes
import hashlib
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.errors import (
    ComputerControlError,
    StaleDesktopFrameError,
    UnsafeInputTargetError,
)
from sim_pilot.computer_control.models import (
    ComputerControlCapabilities,
    DesktopFrame,
    InputExecutionResult,
    InputGesture,
    InputGestureKind,
    WindowBounds,
)

_APPLICATION_SERVICES = Path(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_CORE_GRAPHICS = Path("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_CORE_FOUNDATION = Path("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_HID_EVENT_TAP = 0
_LEFT_MOUSE_DOWN = 1
_LEFT_MOUSE_UP = 2
_LEFT_BUTTON = 0
_MAXIMUM_FRAME_AGE_SECONDS = 2.0


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class MacOSComputerControlBackend:
    """Fail-closed macOS backend for the currently verified fullscreen game path."""

    def __init__(self, application_name: str) -> None:
        if not application_name.strip():
            raise ValueError("application name is required")
        self._application_name = application_name

    def capabilities(self) -> ComputerControlCapabilities:
        trusted = accessibility_trusted()
        return ComputerControlCapabilities(
            platform="macos",
            screen_capture=True,
            accessibility_trusted=trusted,
            click=trusted,
            keyboard=trusted,
            live_verified=trusted,
            detail="CoreGraphics input and screencapture on the active primary display",
        )

    def capture(self, *, process_id: int) -> CapturedDesktopFrame:
        self._activate()
        with tempfile.TemporaryDirectory(prefix="sim-pilot-desktop-") as directory:
            path = Path(directory) / "frame.png"
            completed = subprocess.run(
                ["screencapture", "-x", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0 or not path.is_file():
                raise ComputerControlError(
                    completed.stderr.strip() or "screen capture produced no image"
                )
            encoded = path.read_bytes()
            with Image.open(path) as source:
                image = source.convert("RGB").copy()
        width, height = image.size
        logical = _main_display_bounds()
        if logical.size.width <= 0 or logical.size.height <= 0:
            raise ComputerControlError("CoreGraphics returned invalid display bounds")
        scale_x = width / logical.size.width
        scale_y = height / logical.size.height
        if abs(scale_x - scale_y) > 0.05:
            raise ComputerControlError("screen capture and display scaling are inconsistent")
        digest = hashlib.sha256(encoded).hexdigest()
        metadata = DesktopFrame(
            frame_id=digest,
            captured_at=datetime.now(UTC),
            process_id=process_id,
            window_bounds=WindowBounds(
                x=max(0, round(logical.origin.x)),
                y=max(0, round(logical.origin.y)),
                width=round(logical.size.width),
                height=round(logical.size.height),
            ),
            pixel_width=width,
            pixel_height=height,
            display_scale=scale_x,
            sha256=digest,
        )
        return CapturedDesktopFrame(metadata, image)

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        now = datetime.now(UTC)
        if gesture.expected_process_id != frame.process_id:
            raise StaleDesktopFrameError("game process changed after target resolution")
        if gesture.expected_frame_id != frame.frame_id:
            raise StaleDesktopFrameError("input target belongs to a different screenshot")
        if frame.age_seconds(now) > _MAXIMUM_FRAME_AGE_SECONDS:
            raise StaleDesktopFrameError("input target screenshot is stale")
        if not accessibility_trusted():
            raise ComputerControlError("macOS Accessibility control is disabled")
        self._activate()
        if gesture.kind is InputGestureKind.CLICK:
            assert gesture.point is not None
            if not frame.window_bounds.contains(gesture.point, margin=2):
                raise UnsafeInputTargetError("click target is outside the verified game bounds")
            _post_click(gesture.point.x, gesture.point.y)
        else:
            assert gesture.key_code is not None
            _post_key(gesture.key_code)
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))

    def _activate(self) -> None:
        completed = subprocess.run(
            ["open", "-a", self._application_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ComputerControlError(
                completed.stderr.strip() or f"unable to activate {self._application_name}"
            )
        time.sleep(0.2)


def accessibility_trusted() -> bool:
    services = ctypes.CDLL(str(_APPLICATION_SERVICES))
    function = services.AXIsProcessTrusted
    function.argtypes = []
    function.restype = ctypes.c_bool
    return bool(function())


def _main_display_bounds() -> _CGRect:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    main_display = core_graphics.CGMainDisplayID
    main_display.argtypes = []
    main_display.restype = ctypes.c_uint32
    bounds = core_graphics.CGDisplayBounds
    bounds.argtypes = [ctypes.c_uint32]
    bounds.restype = _CGRect
    return bounds(main_display())


def _post_click(x: int, y: int) -> None:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    core_foundation = ctypes.CDLL(str(_CORE_FOUNDATION))
    create = core_graphics.CGEventCreateMouseEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
    create.restype = ctypes.c_void_p
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    point = _CGPoint(float(x), float(y))
    down = create(None, _LEFT_MOUSE_DOWN, point, _LEFT_BUTTON)
    up = create(None, _LEFT_MOUSE_UP, point, _LEFT_BUTTON)
    if not down or not up:
        if down:
            release(down)
        if up:
            release(up)
        raise ComputerControlError("CoreGraphics could not create mouse events")
    try:
        post(_HID_EVENT_TAP, down)
        time.sleep(0.03)
        post(_HID_EVENT_TAP, up)
    finally:
        release(down)
        release(up)


def _post_key(key_code: int) -> None:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    core_foundation = ctypes.CDLL(str(_CORE_FOUNDATION))
    create = core_graphics.CGEventCreateKeyboardEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    create.restype = ctypes.c_void_p
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    down = create(None, key_code, True)
    up = create(None, key_code, False)
    if not down or not up:
        raise ComputerControlError("CoreGraphics could not create keyboard events")
    try:
        post(_HID_EVENT_TAP, down)
        time.sleep(0.03)
        post(_HID_EVENT_TAP, up)
    finally:
        release(down)
        release(up)
