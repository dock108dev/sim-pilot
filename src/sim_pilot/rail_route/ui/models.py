"""Typed synchronized Rail Route UI observation contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.computer_control.models import DesktopFrame, ScreenPoint
from sim_pilot.game_bridge.models import GameSnapshot


class UIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RailRouteUIScene(StrEnum):
    GAMEPLAY = "gameplay"
    CONSTRUCTION_OPEN = "construction_open"
    UNKNOWN = "unknown"


class SignalScreenTarget(UIModel):
    signal_id: str = Field(min_length=1, max_length=128)
    internal_name: str = Field(min_length=1, max_length=256)
    grid_x: int
    grid_y: int
    point: ScreenPoint
    shape_score: int = Field(ge=0)


class RailRouteUIObservation(UIModel):
    schema_version: Literal[1] = 1
    semantic_before: GameSnapshot
    semantic_after: GameSnapshot
    frame: DesktopFrame
    scene: RailRouteUIScene
    projection_id: str = Field(min_length=64, max_length=64)
    signal_targets: tuple[SignalScreenTarget, ...]


class RailRouteUICapabilities(UIModel):
    schema_version: Literal[1] = 1
    actions: tuple[str, ...]
    mutation_allowed: bool
    reason: str = Field(min_length=1, max_length=512)
