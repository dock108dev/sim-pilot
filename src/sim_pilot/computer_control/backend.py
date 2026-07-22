"""Backend protocol for bounded desktop control."""

from typing import Protocol

from PIL import Image

from .models import ComputerControlCapabilities, DesktopFrame, InputExecutionResult, InputGesture


class CapturedDesktopFrame:
    """Frame metadata plus an in-memory image that is never persisted by default."""

    def __init__(self, metadata: DesktopFrame, image: Image.Image) -> None:
        self.metadata = metadata
        self.image = image


class ComputerControlBackend(Protocol):
    def capabilities(self) -> ComputerControlCapabilities: ...

    def capture(self, *, process_id: int) -> CapturedDesktopFrame: ...

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult: ...
