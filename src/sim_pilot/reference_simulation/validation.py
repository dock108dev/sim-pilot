"""Non-mutating validation for reference simulation actions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.reference_simulation.actions import (
    AdvanceTime,
    BuildHousing,
    BuildPower,
    Pause,
    RepairInfrastructure,
    Resume,
    SetMaintenance,
    SimulationAction,
    TakeLoan,
)
from sim_pilot.reference_simulation.state import SimulationState

HOUSING_COST_PER_UNIT = 1_000.0
POWER_COST_PER_CAPACITY = 1_500.0
REPAIR_COST_PER_POINT = 2_000.0
MINIMUM_LOAN = 10_000.0
MAXIMUM_LOAN = 500_000.0
MAXIMUM_DEBT = 2_000_000.0
MAXIMUM_ACTIVE_PROJECTS = 5


class ValidationResult(BaseModel):
    """The deterministic result of validating an action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    valid: bool
    message: str = Field(min_length=1)
    estimated_cost: float = Field(ge=0)
    state_stale: bool = False


def valid(cost: float = 0.0) -> ValidationResult:
    return ValidationResult(valid=True, message="Action is valid.", estimated_cost=cost)


def invalid(message: str) -> ValidationResult:
    return ValidationResult(valid=False, message=message, estimated_cost=0.0)


def validate_action(state: SimulationState, action: SimulationAction) -> ValidationResult:
    """Validate an action without mutating simulation state."""
    if state.failed:
        return invalid("Simulation has failed and cannot accept actions.")

    if isinstance(action, AdvanceTime):
        if state.paused:
            return invalid("Cannot advance time while the simulation is paused.")
        return valid()

    if isinstance(action, Pause):
        return invalid("Simulation is already paused.") if state.paused else valid()

    if isinstance(action, Resume):
        return valid() if state.paused else invalid("Simulation is not paused.")

    if isinstance(action, (BuildHousing, BuildPower)):
        if len(state.active_projects) >= MAXIMUM_ACTIVE_PROJECTS:
            return invalid("The maximum of five active projects has been reached.")
        cost = (
            action.units * HOUSING_COST_PER_UNIT
            if isinstance(action, BuildHousing)
            else action.capacity * POWER_COST_PER_CAPACITY
        )
        if cost > state.cash:
            return invalid("Insufficient cash to start project.")
        return valid(cost)

    if isinstance(action, RepairInfrastructure):
        if state.infrastructure >= 100:
            return invalid("Infrastructure is already at its maximum.")
        cost = action.amount * REPAIR_COST_PER_POINT
        if cost > state.cash:
            return invalid("Insufficient cash to repair infrastructure.")
        return valid(cost)

    if isinstance(action, SetMaintenance):
        if action.level == state.maintenance_level:
            return invalid("Maintenance is already set to that level.")
        return valid()

    if isinstance(action, TakeLoan):
        if action.amount < MINIMUM_LOAN:
            return invalid("Loan amount is below the minimum of 10000.")
        if action.amount > MAXIMUM_LOAN:
            return invalid("Loan amount exceeds the per-action maximum of 500000.")
        if state.debt + action.amount > MAXIMUM_DEBT:
            return invalid("Loan would exceed the total debt limit of 2000000.")
        return valid()

    if action.amount > state.cash:
        return invalid("Repayment exceeds available cash.")
    if action.amount > state.debt:
        return invalid("Repayment exceeds outstanding debt.")
    return valid(action.amount)
