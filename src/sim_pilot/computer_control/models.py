"""Strict desktop observation and bounded-input contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ScreenPoint(ControlModel):
    # Quartz uses one signed global desktop coordinate space. Displays placed to
    # the left of or above the primary display therefore have negative origins.
    x: int
    y: int


class WindowBounds(ControlModel):
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    def contains(self, point: ScreenPoint, *, margin: int = 0) -> bool:
        return (
            self.x + margin <= point.x < self.x + self.width - margin
            and self.y + margin <= point.y < self.y + self.height - margin
        )


class DesktopWindowIdentity(ControlModel):
    schema_version: Literal[1] = 1
    process_id: int = Field(ge=1)
    window_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=512)
    bounds: WindowBounds
    content_bounds: WindowBounds | None = None
    visible_regions: tuple[WindowBounds, ...] = ()
    display_ids: tuple[str, ...] = ()
    display_scale: float = Field(gt=0, le=4)
    frontmost: bool

    def is_visible(self, point: ScreenPoint, *, margin: int = 0) -> bool:
        regions = self.visible_regions or (self.bounds,)
        return any(region.contains(point, margin=margin) for region in regions)


class DesktopFrame(ControlModel):
    """One exact-window capture event; pixel identity is intentionally separate."""

    schema_version: Literal[2] = 2
    frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_sequence: int = Field(ge=1)
    captured_at: AwareDatetime
    process_id: int = Field(ge=1)
    window_id: str = Field(min_length=1, max_length=256)
    window_title: str = Field(min_length=1, max_length=512)
    window_bounds: WindowBounds
    window_content_bounds: WindowBounds | None = None
    window_visible_regions: tuple[WindowBounds, ...] = ()
    display_ids: tuple[str, ...] = ()
    window_frontmost: Literal[True] = True
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    display_scale: float = Field(gt=0, le=4)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: Literal["macos", "windows"]

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.captured_at).total_seconds())


class InputGestureKind(StrEnum):
    CLICK = "click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    KEY = "key"
    TEXT = "text"
    SCROLL = "scroll"


class KeyModifier(StrEnum):
    COMMAND = "command"
    CONTROL = "control"
    OPTION = "option"
    SHIFT = "shift"


class InputGesture(ControlModel):
    """Strict tagged gesture payload bound to one fresh exact-window frame."""

    schema_version: Literal[2] = 2
    kind: InputGestureKind
    point: ScreenPoint | None = None
    key_code: int | None = Field(default=None, ge=0, le=255)
    modifiers: tuple[KeyModifier, ...] = ()
    text: str | None = Field(default=None, min_length=1, max_length=256)
    scroll_delta_x: int | None = Field(default=None, ge=-100, le=100)
    scroll_delta_y: int | None = Field(default=None, ge=-100, le=100)
    expected_process_id: int = Field(ge=1)
    expected_window_id: str = Field(min_length=1, max_length=256)
    expected_window_bounds: WindowBounds
    expected_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_scene: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=256)
    intended_effect: str = Field(min_length=1, max_length=512)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    maximum_age_seconds: float = Field(default=2.0, gt=0, le=10)

    @model_validator(mode="after")
    def validate_payload(self) -> "InputGesture":
        if len(set(self.modifiers)) != len(self.modifiers):
            raise ValueError("key modifiers must be unique")
        if self.kind in {
            InputGestureKind.CLICK,
            InputGestureKind.RIGHT_CLICK,
            InputGestureKind.MOVE,
        }:
            valid = (
                self.point is not None
                and self.key_code is None
                and not self.modifiers
                and self.text is None
                and self.scroll_delta_x is None
                and self.scroll_delta_y is None
            )
            message = f"{self.kind.value} requires only a point"
        elif self.kind is InputGestureKind.KEY:
            valid = (
                self.point is None
                and self.key_code is not None
                and self.text is None
                and self.scroll_delta_x is None
                and self.scroll_delta_y is None
            )
            message = "key requires only a key code and optional modifiers"
        elif self.kind is InputGestureKind.TEXT:
            valid = (
                self.point is None
                and self.key_code is None
                and not self.modifiers
                and self.text is not None
                and self.scroll_delta_x is None
                and self.scroll_delta_y is None
            )
            message = "text requires only non-empty Unicode text"
        else:
            valid = (
                self.point is not None
                and self.key_code is None
                and not self.modifiers
                and self.text is None
                and self.scroll_delta_x is not None
                and self.scroll_delta_y is not None
                and (self.scroll_delta_x != 0 or self.scroll_delta_y != 0)
            )
            message = "scroll requires a point and a non-zero bounded delta"
        if not valid:
            raise ValueError(message)
        return self

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.created_at).total_seconds())


class InputExecutionResult(ControlModel):
    schema_version: Literal[2] = 2
    gesture: InputGesture
    sent_at: AwareDatetime
    input_sent: Literal[True] = True


class ComputerControlCapabilities(ControlModel):
    schema_version: Literal[2] = 2
    platform: Literal["macos", "windows"]
    exact_window_capture: bool
    screen_capture: bool
    accessibility_trusted: bool
    click: bool
    keyboard: bool
    text: bool
    scrolling: bool
    live_verified: bool
    detail: str = Field(min_length=1, max_length=512)
