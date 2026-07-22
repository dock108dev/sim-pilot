"""Game-neutral, capability-gated desktop observation and input."""

from .models import (
    ComputerControlCapabilities,
    DesktopFrame,
    InputExecutionResult,
    InputGesture,
    InputGestureKind,
    ScreenPoint,
    WindowBounds,
)

__all__ = [
    "ComputerControlCapabilities",
    "DesktopFrame",
    "InputExecutionResult",
    "InputGesture",
    "InputGestureKind",
    "ScreenPoint",
    "WindowBounds",
]
