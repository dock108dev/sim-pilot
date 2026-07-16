"""Success and validation paths for every reference simulation action."""

import pytest

from sim_pilot.reference_simulation import (
    AdvanceTime,
    BuildHousing,
    BuildPower,
    Pause,
    ReferenceSimulation,
    RepairInfrastructure,
    RepayLoan,
    Resume,
    SetMaintenance,
    SimulationAction,
    SimulationState,
    TakeLoan,
)


def test_every_action_success_path() -> None:
    simulation = ReferenceSimulation(SimulationState(cash=2_000_000))

    assert simulation.execute(BuildHousing(units=100)).success
    assert simulation.execute(BuildPower(capacity=200)).success
    assert simulation.execute(RepairInfrastructure(amount=5.0)).success
    assert simulation.execute(SetMaintenance(level=1.0)).success
    assert simulation.execute(TakeLoan(amount=100_000.0)).success
    assert simulation.execute(RepayLoan(amount=50_000.0)).success
    assert simulation.execute(Pause()).success
    assert simulation.execute(Resume()).success
    assert simulation.execute(AdvanceTime(ticks=1)).success


def test_projects_charge_full_cost_at_start_and_allow_duplicates() -> None:
    simulation = ReferenceSimulation()

    first = simulation.execute(BuildHousing(units=100))
    second = simulation.execute(BuildHousing(units=50))

    assert first.cost == 100_000
    assert second.cost == 50_000
    assert simulation.state.cash == 350_000
    assert len(simulation.state.active_projects) == 2


def test_project_limit_is_five() -> None:
    simulation = ReferenceSimulation(SimulationState(cash=10_000_000))
    for _ in range(5):
        assert simulation.execute(BuildHousing(units=1)).success

    result = simulation.execute(BuildPower(capacity=1))

    assert result.success is False
    assert "maximum of five" in result.message


@pytest.mark.parametrize(
    ("simulation", "action", "message"),
    [
        (ReferenceSimulation(SimulationState(paused=True)), AdvanceTime(ticks=1), "paused"),
        (ReferenceSimulation(), Resume(), "not paused"),
        (ReferenceSimulation(SimulationState(paused=True)), Pause(), "already paused"),
        (ReferenceSimulation(), BuildHousing(units=501), "Insufficient cash"),
        (ReferenceSimulation(), BuildPower(capacity=334), "Insufficient cash"),
        (ReferenceSimulation(), RepairInfrastructure(amount=251), "Insufficient cash"),
        (
            ReferenceSimulation(SimulationState(infrastructure=100)),
            RepairInfrastructure(amount=1),
            "maximum",
        ),
        (ReferenceSimulation(), SetMaintenance(level=0.5), "already set"),
        (ReferenceSimulation(), TakeLoan(amount=9_999), "minimum"),
        (ReferenceSimulation(), TakeLoan(amount=500_001), "per-action maximum"),
        (
            ReferenceSimulation(SimulationState(debt=1_900_000)),
            TakeLoan(amount=200_000),
            "total debt limit",
        ),
        (
            ReferenceSimulation(SimulationState(cash=10_000, debt=20_000)),
            RepayLoan(amount=15_000),
            "available cash",
        ),
        (
            ReferenceSimulation(SimulationState(cash=20_000, debt=10_000)),
            RepayLoan(amount=15_000),
            "outstanding debt",
        ),
    ],
)
def test_action_validation_failures(
    simulation: ReferenceSimulation,
    action: SimulationAction,
    message: str,
) -> None:
    original = simulation.state
    result = simulation.execute(action)

    assert result.success is False
    assert message in result.message
    assert simulation.state == original


def test_failed_simulation_rejects_all_actions() -> None:
    simulation = ReferenceSimulation(SimulationState(cash=-1, paused=True, failed=True))

    result = simulation.execute(Resume())

    assert result.success is False
    assert "failed" in result.message


def test_validation_does_not_mutate_state_or_events() -> None:
    simulation = ReferenceSimulation()
    original = simulation.state

    validation = simulation.validate(BuildHousing(units=100))

    assert validation.valid is True
    assert validation.estimated_cost == 100_000
    assert simulation.state == original
    assert simulation.events == ()
