"""Game-neutral, capability-gated desktop observation and input."""

from .models import (
    ComputerControlCapabilities,
    DesktopFrame,
    DesktopWindowIdentity,
    InputExecutionResult,
    InputGesture,
    InputGestureKind,
    KeyModifier,
    ScreenPoint,
    WindowBounds,
)

__all__ = [
    "ComputerControlCapabilities",
    "DesktopFrame",
    "DesktopWindowIdentity",
    "InputExecutionResult",
    "InputGesture",
    "InputGestureKind",
    "KeyModifier",
    "ScreenPoint",
    "WindowBounds",
]
