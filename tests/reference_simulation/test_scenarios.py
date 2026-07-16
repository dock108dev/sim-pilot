"""End-to-end deterministic reference simulation scenarios."""

from pathlib import Path

from sim_pilot.reference_simulation import (
    AdvanceTime,
    BuildHousing,
    BuildPower,
    ReferenceSimulation,
    RepairInfrastructure,
    SetMaintenance,
    SimulationAction,
    SimulationState,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def load_fixture(name: str) -> SimulationState:
    return SimulationState.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


def test_scenario_a_reaches_one_million_with_time_progression() -> None:
    simulation = ReferenceSimulation()
    simulation.execute(SetMaintenance(level=1.0))

    while simulation.state.cash < 1_000_000:
        result = simulation.execute(AdvanceTime(ticks=1))
        assert result.success is True
        assert simulation.state.failed is False

    assert simulation.state.cash >= 1_000_000


def test_scenario_b_maintains_infrastructure_above_seventy() -> None:
    simulation = ReferenceSimulation()

    for _ in range(100):
        if simulation.state.infrastructure <= 75:
            assert simulation.execute(RepairInfrastructure(amount=10)).success
        assert simulation.execute(AdvanceTime(ticks=1)).success
        assert simulation.state.infrastructure >= 70


def test_scenario_d_rejects_unfunded_spending() -> None:
    simulation = ReferenceSimulation(SimulationState(cash=99_999))

    result = simulation.execute(BuildHousing(units=100))

    assert result.success is False
    assert simulation.state.cash == 99_999


def test_scenario_e_reports_cost_without_approval_logic() -> None:
    simulation = ReferenceSimulation()

    validation = simulation.validate(BuildPower(capacity=100))

    assert validation.valid is True
    assert validation.estimated_cost == 150_000
    assert simulation.state.active_projects == ()


def test_scenario_f_reaches_population_two_thousand() -> None:
    simulation = ReferenceSimulation(SimulationState(cash=10_000_000, infrastructure=100))
    assert simulation.execute(BuildHousing(units=2_000)).success
    assert simulation.execute(BuildPower(capacity=2_000)).success
    assert simulation.execute(SetMaintenance(level=1.0)).success

    while simulation.state.population < 2_000:
        assert simulation.execute(AdvanceTime(ticks=1)).success

    assert simulation.state.population >= 2_000
    assert simulation.state.housing >= simulation.state.population
    assert simulation.state.power_capacity >= simulation.state.power_usage


def test_scenario_g_fixture_restoration_replays_identically() -> None:
    initial = load_fixture("low_power_state.json")
    actions: tuple[SimulationAction, ...] = (
        BuildPower(capacity=100),
        AdvanceTime(ticks=8),
        RepairInfrastructure(amount=5),
    )
    first = ReferenceSimulation(initial, seed=42)
    restored = ReferenceSimulation.from_json(first.to_json(), seed=42)

    for action in actions:
        assert first.execute(action) == restored.execute(action)

    assert first.state == restored.state
    assert first.events == restored.events


def test_scenario_h_terminal_failure_rejects_future_actions() -> None:
    simulation = ReferenceSimulation(
        SimulationState(cash=1, population=0, housing=0, power_capacity=0, power_usage=0)
    )

    assert simulation.execute(AdvanceTime(ticks=1)).success
    state_at_failure = simulation.state
    rejected = simulation.execute(RepairInfrastructure(amount=1))

    assert state_at_failure.failed is True
    assert rejected.success is False
    assert simulation.state == state_at_failure


def test_serialization_restores_exact_state() -> None:
    simulation = ReferenceSimulation()
    simulation.execute(BuildHousing(units=100))
    simulation.execute(AdvanceTime(ticks=2))

    restored = ReferenceSimulation.from_json(simulation.to_json())

    assert restored.state == simulation.state
