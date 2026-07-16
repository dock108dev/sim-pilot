"""Typed actions supported by the standalone reference simulation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SimulationActionModel(BaseModel):
    """Strict base for untrusted action inputs."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class AdvanceTime(SimulationActionModel):
    type: Literal["advance_time"] = "advance_time"
    ticks: int = Field(gt=0)


class BuildHousing(SimulationActionModel):
    type: Literal["build_housing"] = "build_housing"
    units: int = Field(gt=0)


class BuildPower(SimulationActionModel):
    type: Literal["build_power"] = "build_power"
    capacity: int = Field(gt=0)


class RepairInfrastructure(SimulationActionModel):
    type: Literal["repair"] = "repair"
    amount: float = Field(gt=0)


class SetMaintenance(SimulationActionModel):
    type: Literal["set_maintenance"] = "set_maintenance"
    level: float

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: float) -> float:
        if value not in {0.0, 0.5, 1.0}:
            msg = "maintenance level must be 0.0, 0.5, or 1.0"
            raise ValueError(msg)
        return value


class TakeLoan(SimulationActionModel):
    type: Literal["take_loan"] = "take_loan"
    amount: float = Field(gt=0)


class RepayLoan(SimulationActionModel):
    type: Literal["repay_loan"] = "repay_loan"
    amount: float = Field(gt=0)


class Pause(SimulationActionModel):
    type: Literal["pause"] = "pause"


class Resume(SimulationActionModel):
    type: Literal["resume"] = "resume"


type SimulationAction = (
    AdvanceTime
    | BuildHousing
    | BuildPower
    | RepairInfrastructure
    | SetMaintenance
    | TakeLoan
    | RepayLoan
    | Pause
    | Resume
)
