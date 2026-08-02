"""Native macOS exact-window screenshot and bounded input primitives."""

from __future__ import annotations

import ctypes
import hashlib
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.errors import (
    ComputerControlError,
    StaleDesktopFrameError,
    UnsafeInputTargetError,
)
from sim_pilot.computer_control.models import (
    ComputerControlCapabilities,
    DesktopFrame,
    DesktopWindowIdentity,
    InputExecutionResult,
    InputGesture,
    InputGestureKind,
    KeyModifier,
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
_RIGHT_MOUSE_DOWN = 3
_RIGHT_MOUSE_UP = 4
_MOUSE_MOVED = 5
_LEFT_BUTTON = 0
_RIGHT_BUTTON = 1
_PIXEL_SCROLL_UNIT = 0
_MAXIMUM_FRAME_AGE_SECONDS = 2.0
_MAXIMUM_REVALIDATABLE_FRAME_AGE_SECONDS = 10.0
_MAXIMUM_REVALIDATION_PIXEL_CHANGE_FRACTION = 0.01
_MAXIMUM_TARGET_PATCH_CHANNEL_DELTA = 24
_MAXIMUM_TARGET_PATCH_RMS_DELTA = 3.0
_TARGET_PATCH_RADIUS_LOGICAL_PIXELS = 5
_CAPTURE_IMAGE_CACHE_SIZE = 3
_FRONTMOST_SETTLE_SECONDS = 0.5
_FRONTMOST_POLL_SECONDS = 0.05
_FRONTMOST_ACTIVATION_ATTEMPTS = 2
_MODIFIER_FLAGS = {
    KeyModifier.SHIFT: 0x00020000,
    KeyModifier.CONTROL: 0x00040000,
    KeyModifier.OPTION: 0x00080000,
    KeyModifier.COMMAND: 0x00100000,
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


WindowResolver = Callable[[int], DesktopWindowIdentity]
Activator = Callable[[], None]
WindowNormalizer = Callable[[int], None]


def _same_window_surface(expected: DesktopFrame, fresh: DesktopFrame) -> bool:
    """Require exact process, window, display, and raster continuity."""
    return (
        fresh.process_id == expected.process_id
        and fresh.window_id == expected.window_id
        and fresh.window_title == expected.window_title
        and fresh.window_bounds == expected.window_bounds
        and fresh.window_content_bounds == expected.window_content_bounds
        and fresh.window_visible_regions == expected.window_visible_regions
        and fresh.display_ids == expected.display_ids
        and fresh.pixel_width == expected.pixel_width
        and fresh.pixel_height == expected.pixel_height
        and abs(fresh.display_scale - expected.display_scale) <= 0.1
    )


def _same_visual_surface(
    expected: DesktopFrame,
    fresh: DesktopFrame,
    *,
    expected_image: Image.Image | None,
    fresh_image: Image.Image,
    gesture: InputGesture,
) -> bool:
    """Allow only bounded background animation outside an exact target patch."""
    if not _same_window_surface(expected, fresh):
        return False
    if fresh.sha256 == expected.sha256:
        return True
    if expected_image is None:
        return False
    expected_rgb = expected_image.convert("RGB")
    fresh_rgb = fresh_image.convert("RGB")
    if expected_rgb.size != fresh_rgb.size:
        return False
    difference = ImageChops.difference(expected_rgb, fresh_rgb)
    histogram = difference.convert("L").histogram()
    changed_pixels = expected.pixel_width * expected.pixel_height - histogram[0]
    if (
        changed_pixels / (expected.pixel_width * expected.pixel_height)
        > _MAXIMUM_REVALIDATION_PIXEL_CHANGE_FRACTION
    ):
        return False
    if gesture.point is None:
        # Focused text fields legitimately blink their caret between semantic
        # observation and native dispatch. Keyboard/text gestures have no pointer
        # target patch, so require exact window continuity plus the same strict
        # global change bound instead of rejecting every non-identical frame.
        return gesture.kind in {InputGestureKind.KEY, InputGestureKind.TEXT}
    left = round(
        (gesture.point.x - expected.window_bounds.x) * expected.display_scale
        - _TARGET_PATCH_RADIUS_LOGICAL_PIXELS * expected.display_scale
    )
    top = round(
        (gesture.point.y - expected.window_bounds.y) * expected.display_scale
        - _TARGET_PATCH_RADIUS_LOGICAL_PIXELS * expected.display_scale
    )
    diameter = round((_TARGET_PATCH_RADIUS_LOGICAL_PIXELS * 2 + 1) * expected.display_scale)
    box = (
        max(0, left),
        max(0, top),
        min(expected.pixel_width, left + diameter),
        min(expected.pixel_height, top + diameter),
    )
    if box[0] >= box[2] or box[1] >= box[3]:
        return False
    if gesture.kind is InputGestureKind.MOVE:
        # Moving the pointer cannot mutate game state. Window continuity and a
        # globally stable frame are sufficient even when the floor under a
        # projected world target has subtle ambient animation.
        return True
    target_difference = difference.crop(box)
    if target_difference.getbbox() is not None:
        statistics = ImageStat.Stat(target_difference)
        maximum_delta = max(maximum for _minimum, maximum in statistics.extrema)
        maximum_rms = max(statistics.rms)
        if (
            maximum_delta > _MAXIMUM_TARGET_PATCH_CHANNEL_DELTA
            or maximum_rms > _MAXIMUM_TARGET_PATCH_RMS_DELTA
        ):
            return False
    return True


class MacOSComputerControlBackend:
    """Fail-closed macOS backend bound to an expected process and window."""

    def __init__(
        self,
        application_name: str,
        *,
        activator: Activator | None = None,
        window_resolver: WindowResolver | None = None,
        window_normalizer: WindowNormalizer | None = None,
    ) -> None:
        if not application_name.strip():
            raise ValueError("application name is required")
        self._application_name = application_name
        self._activator = activator or self._legacy_activate
        self._window_resolver = window_resolver or self._primary_display_window
        self._window_normalizer = window_normalizer
        self._exact_window = window_resolver is not None
        self._capture_sequence = 0
        self._capture_images: dict[str, Image.Image] = {}

    def capabilities(self) -> ComputerControlCapabilities:
        trusted = accessibility_trusted()
        return ComputerControlCapabilities(
            platform="macos",
            exact_window_capture=self._exact_window,
            screen_capture=True,
            accessibility_trusted=trusted,
            click=trusted,
            keyboard=trusted,
            text=trusted,
            scrolling=trusted,
            live_verified=False,
            detail=(
                "CoreGraphics input and exact-window screencapture"
                if self._exact_window
                else "legacy primary-display capture; exact-window targeting unavailable"
            ),
        )

    def capture(self, *, process_id: int) -> CapturedDesktopFrame:
        before = self._activate_and_resolve_window(process_id, normalize=True)
        if before.process_id != process_id:
            raise ComputerControlError("window resolver returned a different process")
        if not before.frontmost:
            raise ComputerControlError("expected game window is not frontmost")
        bounds = before.bounds
        with tempfile.TemporaryDirectory(prefix="sim-pilot-desktop-") as directory:
            path = Path(directory) / "frame.png"
            region = f"{bounds.x},{bounds.y},{bounds.width},{bounds.height}"
            completed = subprocess.run(
                ["screencapture", "-x", f"-R{region}", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0 or not path.is_file():
                raise ComputerControlError(
                    completed.stderr.strip() or "exact-window screen capture produced no image"
                )
            encoded = path.read_bytes()
            with Image.open(path) as source:
                image = source.convert("RGB").copy()
        after = self._window_resolver(process_id)
        if after != before:
            raise StaleDesktopFrameError("game window changed during screen capture")
        width, height = image.size
        scale_x = width / bounds.width
        scale_y = height / bounds.height
        if abs(scale_x - scale_y) > 0.05 or abs(scale_x - before.display_scale) > 0.1:
            raise ComputerControlError("screen capture and exact-window scaling are inconsistent")
        digest = hashlib.sha256(encoded).hexdigest()
        self._capture_sequence += 1
        captured_at = datetime.now(UTC)
        identity_material = "|".join(
            (
                str(process_id),
                before.window_id,
                str(self._capture_sequence),
                str(time.time_ns()),
                digest,
            )
        )
        frame_id = hashlib.sha256(identity_material.encode()).hexdigest()
        metadata = DesktopFrame(
            frame_id=frame_id,
            capture_sequence=self._capture_sequence,
            captured_at=captured_at,
            process_id=process_id,
            window_id=before.window_id,
            window_title=before.title,
            window_bounds=bounds,
            window_content_bounds=before.content_bounds,
            window_visible_regions=before.visible_regions,
            display_ids=before.display_ids,
            window_frontmost=True,
            pixel_width=width,
            pixel_height=height,
            display_scale=scale_x,
            sha256=digest,
            platform="macos",
        )
        capture = CapturedDesktopFrame(metadata, image)
        self._capture_images[frame_id] = image
        while len(self._capture_images) > _CAPTURE_IMAGE_CACHE_SIZE:
            del self._capture_images[next(iter(self._capture_images))]
        return capture

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        now = datetime.now(UTC)
        if gesture.expected_process_id != frame.process_id:
            raise StaleDesktopFrameError("game process changed after target resolution")
        if gesture.expected_window_id != frame.window_id:
            raise StaleDesktopFrameError("game window changed after target resolution")
        if gesture.expected_window_bounds != frame.window_bounds:
            raise StaleDesktopFrameError("game window bounds changed after target resolution")
        if gesture.expected_frame_id != frame.frame_id:
            raise StaleDesktopFrameError("input target belongs to a different screenshot")
        maximum_gesture_age = min(_MAXIMUM_FRAME_AGE_SECONDS, gesture.maximum_age_seconds)
        if gesture.age_seconds(now) > maximum_gesture_age:
            raise StaleDesktopFrameError("input gesture is stale")
        if frame.age_seconds(now) > _MAXIMUM_REVALIDATABLE_FRAME_AGE_SECONDS:
            raise StaleDesktopFrameError("input target screenshot is too old to revalidate")
        if not accessibility_trusted():
            raise ComputerControlError("macOS Accessibility control is disabled")
        current = self._activate_and_resolve_window(frame.process_id, normalize=False)
        if not current.frontmost:
            raise StaleDesktopFrameError("game window is not frontmost")
        refreshed = datetime.now(UTC)
        if gesture.age_seconds(refreshed) > maximum_gesture_age:
            raise StaleDesktopFrameError("input gesture became stale while foregrounding")
        if (
            current.window_id != frame.window_id
            or current.title != frame.window_title
            or current.bounds != frame.window_bounds
            or abs(current.display_scale - frame.display_scale) > 0.1
        ):
            differences: list[str] = []
            if current.window_id != frame.window_id:
                differences.append(f"window_id {frame.window_id!r}->{current.window_id!r}")
            if current.title != frame.window_title:
                differences.append(f"title {frame.window_title!r}->{current.title!r}")
            if current.bounds != frame.window_bounds:
                differences.append(f"bounds {frame.window_bounds!r}->{current.bounds!r}")
            if abs(current.display_scale - frame.display_scale) > 0.1:
                differences.append(
                    f"display_scale {frame.display_scale!r}->{current.display_scale!r}"
                )
            raise StaleDesktopFrameError(
                "game window identity changed before input: " + "; ".join(differences)
            )
        verified_frame = frame
        if frame.age_seconds(refreshed) > _MAXIMUM_FRAME_AGE_SECONDS:
            expected_image = self._capture_images.get(frame.frame_id)
            fresh_capture = self.capture(process_id=frame.process_id)
            fresh = fresh_capture.metadata
            if not _same_visual_surface(
                frame,
                fresh,
                expected_image=expected_image,
                fresh_image=fresh_capture.image,
                gesture=gesture,
            ):
                raise StaleDesktopFrameError(
                    "input target screenshot pixels changed during exact revalidation"
                )
            verified_frame = fresh
        visible_regions = verified_frame.window_visible_regions or (verified_frame.window_bounds,)
        if gesture.point is not None and not any(
            region.contains(gesture.point, margin=2) for region in visible_regions
        ):
            raise UnsafeInputTargetError(
                "input target is outside the verified visible game regions"
            )
        if gesture.kind is InputGestureKind.CLICK:
            assert gesture.point is not None
            _post_click(gesture.point.x, gesture.point.y)
        elif gesture.kind is InputGestureKind.RIGHT_CLICK:
            assert gesture.point is not None
            _post_click(gesture.point.x, gesture.point.y, right=True)
        elif gesture.kind is InputGestureKind.MOVE:
            assert gesture.point is not None
            core_graphics, core_foundation = _core_graphics_events()
            _move_pointer(
                core_graphics,
                core_foundation,
                _CGPoint(float(gesture.point.x), float(gesture.point.y)),
            )
        elif gesture.kind is InputGestureKind.KEY:
            assert gesture.key_code is not None
            _post_key(gesture.key_code, gesture.modifiers)
        elif gesture.kind is InputGestureKind.TEXT:
            assert gesture.text is not None
            _post_text(gesture.text)
        else:
            assert gesture.point is not None
            assert gesture.scroll_delta_x is not None and gesture.scroll_delta_y is not None
            _post_scroll(
                gesture.point.x,
                gesture.point.y,
                gesture.scroll_delta_x,
                gesture.scroll_delta_y,
            )
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))

    def _resolve_frontmost_window(self, process_id: int) -> DesktopWindowIdentity:
        """Wait briefly for a full-screen Space activation to reach CoreGraphics."""
        deadline = time.monotonic() + _FRONTMOST_SETTLE_SECONDS
        current = self._window_resolver(process_id)
        while not current.frontmost and time.monotonic() < deadline:
            time.sleep(_FRONTMOST_POLL_SECONDS)
            current = self._window_resolver(process_id)
        return current

    def _activate_and_resolve_window(
        self, process_id: int, *, normalize: bool
    ) -> DesktopWindowIdentity:
        """Retry only reversible activation, never a gameplay input gesture."""
        current: DesktopWindowIdentity | None = None
        for _attempt in range(_FRONTMOST_ACTIVATION_ATTEMPTS):
            self._activator()
            if normalize and self._window_normalizer is not None:
                self._window_normalizer(process_id)
            current = self._resolve_frontmost_window(process_id)
            if current.frontmost:
                return current
        assert current is not None
        return current

    def _legacy_activate(self) -> None:
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

    def _primary_display_window(self, process_id: int) -> DesktopWindowIdentity:
        logical = _main_display_bounds()
        if logical.size.width <= 0 or logical.size.height <= 0:
            raise ComputerControlError("CoreGraphics returned invalid display bounds")
        bounds = WindowBounds(
            x=max(0, round(logical.origin.x)),
            y=max(0, round(logical.origin.y)),
            width=round(logical.size.width),
            height=round(logical.size.height),
        )
        return DesktopWindowIdentity(
            process_id=process_id,
            window_id=f"legacy-primary-display:{process_id}",
            title=self._application_name,
            bounds=bounds,
            display_scale=_main_display_scale(bounds),
            frontmost=True,
        )


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


def _main_display_scale(bounds: WindowBounds) -> float:
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    main_display = core_graphics.CGMainDisplayID
    main_display.argtypes = []
    main_display.restype = ctypes.c_uint32
    pixel_width = core_graphics.CGDisplayPixelsWide
    pixel_width.argtypes = [ctypes.c_uint32]
    pixel_width.restype = ctypes.c_size_t
    return float(pixel_width(main_display())) / bounds.width


def _core_graphics_events() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    return ctypes.CDLL(str(_CORE_GRAPHICS)), ctypes.CDLL(str(_CORE_FOUNDATION))


def _move_pointer(
    core_graphics: ctypes.CDLL, core_foundation: ctypes.CDLL, point: _CGPoint
) -> None:
    create = core_graphics.CGEventCreateMouseEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
    create.restype = ctypes.c_void_p
    warp = core_graphics.CGWarpMouseCursorPosition
    warp.argtypes = [_CGPoint]
    warp.restype = ctypes.c_int32
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    moved = create(None, _MOUSE_MOVED, point, _LEFT_BUTTON)
    if not moved:
        raise ComputerControlError("CoreGraphics could not create pointer event")
    try:
        if warp(point) != 0:
            raise ComputerControlError("CoreGraphics could not move the pointer")
        post(_HID_EVENT_TAP, moved)
    finally:
        release(moved)


def _post_click(x: int, y: int, *, right: bool = False) -> None:
    core_graphics, core_foundation = _core_graphics_events()
    create = core_graphics.CGEventCreateMouseEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
    create.restype = ctypes.c_void_p
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    point = _CGPoint(float(x), float(y))
    _move_pointer(core_graphics, core_foundation, point)
    button = _RIGHT_BUTTON if right else _LEFT_BUTTON
    down_kind = _RIGHT_MOUSE_DOWN if right else _LEFT_MOUSE_DOWN
    up_kind = _RIGHT_MOUSE_UP if right else _LEFT_MOUSE_UP
    down = create(None, down_kind, point, button)
    up = create(None, up_kind, point, button)
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


def _post_key(key_code: int, modifiers: tuple[KeyModifier, ...]) -> None:
    core_graphics, core_foundation = _core_graphics_events()
    create = core_graphics.CGEventCreateKeyboardEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    create.restype = ctypes.c_void_p
    set_flags = core_graphics.CGEventSetFlags
    set_flags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    flags = sum(_MODIFIER_FLAGS[modifier] for modifier in modifiers)
    down = create(None, key_code, True)
    up = create(None, key_code, False)
    if not down or not up:
        if down:
            release(down)
        if up:
            release(up)
        raise ComputerControlError("CoreGraphics could not create keyboard events")
    try:
        set_flags(down, flags)
        set_flags(up, flags)
        post(_HID_EVENT_TAP, down)
        time.sleep(0.03)
        post(_HID_EVENT_TAP, up)
    finally:
        release(down)
        release(up)


def _post_text(value: str) -> None:
    core_graphics, core_foundation = _core_graphics_events()
    create = core_graphics.CGEventCreateKeyboardEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    create.restype = ctypes.c_void_p
    set_unicode = core_graphics.CGEventKeyboardSetUnicodeString
    set_unicode.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    encoded = value.encode("utf-16-le")
    units = (ctypes.c_uint16 * (len(encoded) // 2)).from_buffer_copy(encoded)
    event = create(None, 0, True)
    if not event:
        raise ComputerControlError("CoreGraphics could not create text event")
    try:
        set_unicode(event, len(units), units)
        post(_HID_EVENT_TAP, event)
    finally:
        release(event)


def _post_scroll(x: int, y: int, delta_x: int, delta_y: int) -> None:
    core_graphics, core_foundation = _core_graphics_events()
    point = _CGPoint(float(x), float(y))
    _move_pointer(core_graphics, core_foundation, point)
    create = core_graphics.CGEventCreateScrollWheelEvent
    create.restype = ctypes.c_void_p
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    event = create(None, _PIXEL_SCROLL_UNIT, 2, delta_y, delta_x)
    if not event:
        raise ComputerControlError("CoreGraphics could not create scroll event")
    try:
        post(_HID_EVENT_TAP, event)
    finally:
        release(event)
