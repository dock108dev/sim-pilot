"""Strict Rail Route discovery, observation, and control models."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RailRouteAction(StrEnum):
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"


class RailRouteScreenState(StrEnum):
    PAUSED = "paused"
    RUNNING = "running"
    OTHER_SPEED = "other_speed"
    NOT_GAMEPLAY = "not_gameplay"
    UNKNOWN = "unknown"


class RailRouteInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    app_path: Path
    executable_path: Path
    version: str
    steam_app_id: str | None = None
    steam_build_id: str | None = None
    process_id: int | None = Field(default=None, ge=1)
    running: bool
    accessibility_enabled: bool
    supported: bool
    compatibility_reason: str


class RailRouteObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    observed_at: datetime
    installation: RailRouteInstallation
    screen_state: RailRouteScreenState
    screen_width: int = Field(gt=0)
    screen_height: int = Field(gt=0)
    pause_score: int = Field(ge=0)
    normal_speed_score: int = Field(ge=0)
    accelerated_speed_score: int = Field(ge=0)


class RailRouteIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    instruction: str = Field(min_length=1)
    action: RailRouteAction


class RailRouteControlResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    intent: RailRouteIntent
    before: RailRouteObservation
    after: RailRouteObservation
    input_sent: bool
    verified: bool
    message: str
