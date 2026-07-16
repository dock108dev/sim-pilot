"""Tests for deterministic tick processing and project progression."""

from uuid import UUID

import pytest

from sim_pilot.reference_simulation import Project, ProjectType, SimulationState
from sim_pilot.reference_simulation.state import EventType
from sim_pilot.reference_simulation.tick import advance_tick


def test_tick_applies_formulas_in_canonical_order() -> None:
    result = advance_tick(SimulationState())

    assert result.state.tick == 1
    assert result.state.population == 505
    assert result.state.power_usage == 505
    assert result.state.income_per_tick == 9_090
    assert result.state.expense_per_tick == 2_500
    assert result.state.cash == 506_590
    assert result.state.infrastructure == 89
    assert [event.type for event in result.events] == [
        EventType.TICK_ADVANCED,
        EventType.POPULATION_CHANGED,
        EventType.CASH_CHANGED,
        EventType.INFRASTRUCTURE_CHANGED,
    ]


def test_project_completion_precedes_growth_and_income() -> None:
    project = Project(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        type=ProjectType.POWER,
        amount=200,
        progress=7,
        duration=8,
        remaining_ticks=1,
        total_cost=300_000,
    )
    state = SimulationState(
        population=700,
        housing=800,
        power_capacity=700,
        power_usage=700,
        active_projects=(project,),
    )

    result = advance_tick(state)

    assert result.state.power_capacity == 900
    assert result.state.population == 707
    assert result.state.active_projects == ()
    event_types = [event.type for event in result.events]
    assert event_types.index(EventType.PROJECT_COMPLETED) < event_types.index(
        EventType.POPULATION_CHANGED
    )


def test_concurrent_projects_progress_and_complete_independently() -> None:
    projects = (
        Project(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            type=ProjectType.HOUSING,
            amount=100,
            progress=4,
            duration=5,
            remaining_ticks=1,
            total_cost=100_000,
        ),
        Project(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            type=ProjectType.POWER,
            amount=200,
            progress=6,
            duration=8,
            remaining_ticks=2,
            total_cost=300_000,
        ),
    )

    result = advance_tick(SimulationState(active_projects=projects))

    assert result.state.housing == 700
    assert result.state.power_capacity == 700
    assert len(result.state.active_projects) == 1
    assert result.state.active_projects[0].remaining_ticks == 1


def test_tick_enters_terminal_failure() -> None:
    state = SimulationState(cash=1, population=0, housing=0, power_capacity=0, power_usage=0)

    result = advance_tick(state)

    assert result.state.failed is True
    assert result.state.paused is True
    assert result.failure is not None
    assert result.events[-1].type is EventType.SIMULATION_FAILED


@pytest.mark.parametrize(
    "state",
    [
        SimulationState(
            cash=1,
            population=0,
            housing=0,
            power_capacity=0,
            power_usage=0,
        ),
        SimulationState(infrastructure=0.25, maintenance_level=1.0),
        SimulationState(debt=2_000_001),
    ],
)
def test_all_failure_conditions_are_terminal(state: SimulationState) -> None:
    result = advance_tick(state)

    assert result.state.failed is True
    assert result.state.paused is True
    assert result.failure is not None
