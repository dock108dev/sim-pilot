"""Direct macOS primitives for Rail Route activation and keyboard control."""

import ctypes
import subprocess
import time
from pathlib import Path

_APPLICATION_SERVICES = Path(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_CORE_GRAPHICS = Path("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_CORE_FOUNDATION = Path("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_HID_EVENT_TAP = 0
_SPACE_KEY_CODE = 49


def accessibility_trusted() -> bool:
    """Return the native Accessibility trust decision for this terminal process."""
    services = ctypes.CDLL(str(_APPLICATION_SERVICES))
    function = services.AXIsProcessTrusted
    function.argtypes = []
    function.restype = ctypes.c_bool
    return bool(function())


def activate_rail_route() -> None:
    """Bring Rail Route forward without using Apple Events or System Events."""
    completed = subprocess.run(
        ["open", "-a", "Rail Route"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "unable to activate Rail Route")
    time.sleep(0.2)


def send_space_key() -> None:
    """Post one Space key press through CoreGraphics, requiring Accessibility trust."""
    core_graphics = ctypes.CDLL(str(_CORE_GRAPHICS))
    core_foundation = ctypes.CDLL(str(_CORE_FOUNDATION))
    create = core_graphics.CGEventCreateKeyboardEvent
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    create.restype = ctypes.c_void_p
    post = core_graphics.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    post.restype = None
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None

    key_down = create(None, _SPACE_KEY_CODE, True)
    key_up = create(None, _SPACE_KEY_CODE, False)
    if not key_down or not key_up:
        if key_down:
            release(key_down)
        if key_up:
            release(key_up)
        raise RuntimeError("CoreGraphics could not create the Space key events")
    try:
        post(_HID_EVENT_TAP, key_down)
        time.sleep(0.03)
        post(_HID_EVENT_TAP, key_up)
    finally:
        release(key_down)
        release(key_up)
