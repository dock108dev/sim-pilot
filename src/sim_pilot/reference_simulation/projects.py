"""Reference simulation project models and progression rules."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectType(StrEnum):
    """Long-running project types supported by the simulation."""

    HOUSING = "housing"
    POWER = "power"


class Project(BaseModel):
    """An immutable project progressing once per simulation tick."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    id: UUID
    type: ProjectType
    amount: int = Field(gt=0)
    progress: int = Field(ge=0)
    duration: int = Field(gt=0)
    remaining_ticks: int = Field(ge=0)
    total_cost: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_progress(self) -> "Project":
        if self.progress > self.duration:
            msg = "project progress cannot exceed duration"
            raise ValueError(msg)
        if self.progress + self.remaining_ticks != self.duration:
            msg = "project progress and remaining ticks must equal duration"
            raise ValueError(msg)
        return self


def progress_project(project: Project) -> Project:
    """Advance a project by exactly one tick."""
    remaining_ticks = max(project.remaining_ticks - 1, 0)
    return project.model_copy(
        update={
            "progress": project.duration - remaining_ticks,
            "remaining_ticks": remaining_ticks,
        }
    )
