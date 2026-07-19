"""Reference simulation state and event models."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sim_pilot.reference_simulation.projects import Project

type EventValue = None | bool | int | float | str


class EventType(StrEnum):
    """Events emitted by deterministic simulation transitions."""

    TICK_ADVANCED = "tick_advanced"
    PROJECT_STARTED = "project_started"
    PROJECT_PROGRESSED = "project_progressed"
    PROJECT_COMPLETED = "project_completed"
    INFRASTRUCTURE_CHANGED = "infrastructure_changed"
    POPULATION_CHANGED = "population_changed"
    CASH_CHANGED = "cash_changed"
    DEBT_CHANGED = "debt_changed"
    MAINTENANCE_CHANGED = "maintenance_changed"
    SIMULATION_PAUSED = "simulation_paused"
    SIMULATION_RESUMED = "simulation_resumed"
    SIMULATION_FAILED = "simulation_failed"


class FailureCode(StrEnum):
    """Terminal failure reasons."""

    NEGATIVE_CASH = "negative_cash"
    INFRASTRUCTURE_DEPLETED = "infrastructure_depleted"
    DEBT_LIMIT_EXCEEDED = "debt_limit_exceeded"


class SimulationFailure(BaseModel):
    """A typed explanation of a terminal failure state."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    code: FailureCode
    message: str = Field(min_length=1)


class SimulationEvent(BaseModel):
    """A deterministic event emitted by a state transition."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    tick: int = Field(ge=0)
    type: EventType
    details: dict[str, EventValue] = Field(default_factory=dict)


class SimulationState(BaseModel):
    """An immutable, serializable reference simulation snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    tick: int = Field(default=0, ge=0)
    cash: float = Field(default=500_000)
    debt: float = Field(default=0, ge=0)
    population: int = Field(default=500, ge=0)
    housing: int = Field(default=600, ge=0)
    power_capacity: int = Field(default=700, ge=0)
    power_usage: int = Field(default=500, ge=0)
    infrastructure: float = Field(default=90.0, ge=0, le=100)
    maintenance_level: float = 0.5
    income_per_tick: float = Field(default=0, ge=0)
    expense_per_tick: float = Field(default=0, ge=0)
    paused: bool = False
    failed: bool = False
    active_projects: tuple[Project, ...] = ()

    @field_validator("maintenance_level")
    @classmethod
    def validate_maintenance_level(cls, value: float) -> float:
        if value not in {0.0, 0.5, 1.0}:
            msg = "maintenance level must be 0.0, 0.5, or 1.0"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_failure_state(self) -> "SimulationState":
        """A terminal failure must also leave progression paused."""
        if self.failed and not self.paused:
            msg = "a failed simulation must be paused"
            raise ValueError(msg)
        if self.power_usage != self.population:
            msg = "power_usage must equal population"
            raise ValueError(msg)
        if len(self.active_projects) > 5:
            msg = "active_projects cannot contain more than five projects"
            raise ValueError(msg)
        return self


def initial_state() -> SimulationState:
    """Return the canonical reference-simulation initial state."""
    return SimulationState()
