"""Deterministic action-verification tests."""

from datetime import UTC, datetime

import pytest

from sim_pilot.domain import ExecutionResult, Observation
from sim_pilot.runtime.verification import ActionVerifier
from tests.runtime.helpers import make_action


def observation(tick: int = 0, **state: object) -> Observation:
    return Observation(
        sequence=tick + 1,
        timestamp=datetime.now(UTC),
        tick=tick,
        summary="State.",
        state=state,
    )


@pytest.mark.parametrize(
    ("action_type", "parameters", "before", "after"),
    [
        ("advance_time", {"ticks": 1}, observation(0), observation(1)),
        (
            "build_housing",
            {"units": 1},
            observation(active_projects=[]),
            observation(active_projects=[{"type": "housing"}]),
        ),
        (
            "build_power",
            {"capacity": 1},
            observation(active_projects=[]),
            observation(active_projects=[{"type": "power"}]),
        ),
        ("repair", {"amount": 1}, observation(infrastructure=50), observation(infrastructure=51)),
        (
            "set_maintenance",
            {"level": 1.0},
            observation(maintenance_level=0.5),
            observation(maintenance_level=1.0),
        ),
        ("take_loan", {"amount": 10_000}, observation(debt=0), observation(debt=10_000)),
        ("repay_loan", {"amount": 5_000}, observation(debt=10_000), observation(debt=5_000)),
        ("pause", {}, observation(paused=False), observation(paused=True)),
        ("resume", {}, observation(paused=True), observation(paused=False)),
    ],
)
def test_verifies_every_reference_action(
    action_type: str,
    parameters: dict[str, int | float],
    before: Observation,
    after: Observation,
) -> None:
    result = ActionVerifier().verify(
        before,
        make_action(action_type, **parameters),
        ExecutionResult(success=True, state_changed=True, cost=0, message="Executed."),
        after,
        0,
    )
    assert result.verified


def test_detects_false_success_and_incorrect_cost() -> None:
    state = observation(cash=100)
    result = ActionVerifier().verify(
        state,
        make_action("repair", amount=1),
        ExecutionResult(success=True, state_changed=True, cost=1, message="Executed."),
        state,
        2,
    )
    assert not result.verified
    assert "did not change state" in "; ".join(result.reasons)
    assert "cost" in "; ".join(result.reasons)


def test_detects_failed_execution_that_mutates_state() -> None:
    result = ActionVerifier().verify(
        observation(cash=100),
        make_action("repair", amount=1),
        ExecutionResult(success=False, state_changed=True, cost=0, message="Failed."),
        observation(cash=99),
        0,
    )
    assert not result.verified
    assert "unexpectedly mutated" in "; ".join(result.reasons)
