"""State validation and canonical economy formula tests."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from sim_pilot.reference_simulation import Project, ProjectType, SimulationState
from sim_pilot.reference_simulation.economy import (
    calculate_income,
    calculate_population_growth,
    debt_expense,
    infrastructure_degradation,
    maintenance_cost,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_initial_state_matches_canonical_fixture() -> None:
    state = SimulationState.model_validate_json(
        (FIXTURES / "initial_state.json").read_text(encoding="utf-8")
    )

    assert state == SimulationState()
    assert state.power_usage == state.population


@pytest.mark.parametrize(
    "fixture_name",
    ["initial_state.json", "cash_target_state.json", "bankrupt_state.json", "low_power_state.json"],
)
def test_every_canonical_fixture_loads_as_simulation_state(fixture_name: str) -> None:
    state = SimulationState.model_validate_json(
        (FIXTURES / fixture_name).read_text(encoding="utf-8")
    )

    assert state.schema_version == 1


def test_state_is_immutable_and_rejects_extra_fields() -> None:
    state = SimulationState()

    with pytest.raises(ValidationError, match="frozen"):
        state.tick = 1
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SimulationState.model_validate({**state.model_dump(), "unknown": True})


def test_schema_version_is_validated() -> None:
    payload = SimulationState().model_dump()
    payload["schema_version"] = 2

    with pytest.raises(ValidationError, match="Input should be 1"):
        SimulationState.model_validate(payload)


def test_project_rejects_inconsistent_progress() -> None:
    with pytest.raises(ValidationError, match="must equal duration"):
        Project(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            type=ProjectType.HOUSING,
            amount=100,
            progress=2,
            duration=5,
            remaining_ticks=2,
            total_cost=100_000,
        )


def test_state_rejects_inconsistent_power_usage() -> None:
    with pytest.raises(ValidationError, match="power_usage must equal population"):
        SimulationState(power_usage=499)


def test_population_growth_uses_housing_and_power_limits() -> None:
    assert calculate_population_growth(SimulationState()) == 5
    assert calculate_population_growth(SimulationState(housing=503)) == 3
    assert calculate_population_growth(SimulationState(power_capacity=503)) == 3


@pytest.mark.parametrize(
    "state",
    [
        SimulationState(infrastructure=39),
        SimulationState(power_capacity=499),
        SimulationState(housing=500),
        SimulationState(paused=True),
        SimulationState(paused=True, failed=True),
    ],
)
def test_population_growth_stops_at_canonical_boundaries(state: SimulationState) -> None:
    assert calculate_population_growth(state) == 0


def test_income_applies_infrastructure_and_power_penalties() -> None:
    assert calculate_income(SimulationState()) == 9_000
    assert calculate_income(SimulationState(power_capacity=499)) == 4_500


def test_recurring_expense_formulas() -> None:
    assert maintenance_cost(0.0) == 0
    assert maintenance_cost(0.5) == 2_500
    assert maintenance_cost(1.0) == 5_000
    assert infrastructure_degradation(0.0) == 2.0
    assert infrastructure_degradation(0.5) == 1.0
    assert infrastructure_degradation(1.0) == 0.25
    assert debt_expense(100_000) == 100
