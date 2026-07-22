"""Strict desktop observation and bounded-input contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ScreenPoint(ControlModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class WindowBounds(ControlModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    def contains(self, point: ScreenPoint, *, margin: int = 0) -> bool:
        return (
            self.x + margin <= point.x < self.x + self.width - margin
            and self.y + margin <= point.y < self.y + self.height - margin
        )


class DesktopFrame(ControlModel):
    schema_version: Literal[1] = 1
    frame_id: str = Field(min_length=64, max_length=64)
    captured_at: AwareDatetime
    process_id: int = Field(ge=1)
    window_bounds: WindowBounds
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    display_scale: float = Field(gt=0, le=4)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.captured_at).total_seconds())


class InputGestureKind(StrEnum):
    CLICK = "click"
    KEY = "key"


class InputGesture(ControlModel):
    schema_version: Literal[1] = 1
    kind: InputGestureKind
    point: ScreenPoint | None = None
    key_code: int | None = Field(default=None, ge=0, le=255)
    expected_process_id: int = Field(ge=1)
    expected_frame_id: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_payload(self) -> "InputGesture":
        if self.kind is InputGestureKind.CLICK and (
            self.point is None or self.key_code is not None
        ):
            raise ValueError("click requires only a point")
        if self.kind is InputGestureKind.KEY and (self.key_code is None or self.point is not None):
            raise ValueError("key gesture requires only a key code")
        return self


class InputExecutionResult(ControlModel):
    schema_version: Literal[1] = 1
    gesture: InputGesture
    sent_at: AwareDatetime
    input_sent: Literal[True] = True


class ComputerControlCapabilities(ControlModel):
    schema_version: Literal[1] = 1
    platform: Literal["macos", "windows"]
    screen_capture: bool
    accessibility_trusted: bool
    click: bool
    keyboard: bool
    live_verified: bool
    detail: str = Field(min_length=1, max_length=512)
