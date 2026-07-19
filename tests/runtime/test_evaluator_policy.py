"""Progress evaluator and policy engine unit tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sim_pilot.domain import (
    AuthorityPolicy,
    Constraint,
    ConstraintType,
    Objective,
    ObjectiveType,
    Observation,
    TaskSpecification,
)
from sim_pilot.reference_simulation.validation import ValidationResult
from sim_pilot.runtime.evaluator import ProgressEvaluator
from sim_pilot.runtime.models import EvaluationStatus
from sim_pilot.runtime.policy import PolicyEngine
from tests.runtime.helpers import make_action


def observation(**state: object) -> Observation:
    return Observation(
        sequence=1,
        timestamp=datetime.now(UTC),
        tick=0,
        summary="State.",
        state=state,
    )


def specification(
    *,
    constraints: tuple[Constraint, ...] = (),
    authority: AuthorityPolicy | None = None,
    stop_conditions: tuple[str, ...] = (),
) -> TaskSpecification:
    return TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach cash.",
            parameters={"resource": "cash", "target": 100},
        ),
        constraints=constraints,
        authority=authority or AuthorityPolicy(),
        stop_conditions=stop_conditions,
    )


@pytest.mark.parametrize(("cash", "complete"), [(99, False), (100, True), (101, True)])
def test_objective_completion(cash: int, complete: bool) -> None:
    result = ProgressEvaluator().evaluate(specification(), observation(cash=cash))
    assert result.complete is complete


def test_maintain_and_run_until_objectives() -> None:
    evaluator = ProgressEvaluator()
    maintain = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.MAINTAIN_RESOURCE,
            description="Maintain infrastructure.",
            parameters={"resource": "infrastructure", "target": 70, "direction": "above"},
        ),
        authority=AuthorityPolicy(),
    )
    run_until = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.RUN_UNTIL,
            description="Run until tick ten.",
            parameters={"resource": "tick", "target": 10, "direction": "above"},
        ),
        authority=AuthorityPolicy(),
    )
    assert evaluator.evaluate(maintain, observation(infrastructure=75)).complete
    assert evaluator.evaluate(run_until, observation(tick=10)).complete


def test_project_completion_requires_project_evidence_during_task() -> None:
    project = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.COMPLETE_PROJECT,
            description="Complete housing.",
            parameters={"project_type": "housing"},
        ),
        authority=AuthorityPolicy(),
    )
    evaluator = ProgressEvaluator()
    initial = observation(active_projects=[])
    active = observation(active_projects=[{"type": "housing"}])

    assert not evaluator.evaluate(project, initial).complete
    assert "has not started" in evaluator.evaluate(project, initial).progress_summary
    assert not evaluator.evaluate(project, active, observation_history=(initial,)).complete
    assert evaluator.evaluate(
        project,
        initial,
        observation_history=(initial, active),
    ).complete


def test_stop_condition_blocks() -> None:
    result = ProgressEvaluator().evaluate(
        specification(stop_conditions=("infrastructure < 40",)),
        observation(cash=0, infrastructure=39),
    )
    assert result.current_status is EvaluationStatus.BLOCKED
    assert result.stop_condition_met


def test_satisfied_objective_wins_over_duplicate_stop_condition() -> None:
    run_until = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.RUN_UNTIL,
            description="Run until debt is at or below 25,000.",
            parameters={"resource": "debt", "target": 25_000, "direction": "below"},
        ),
        authority=AuthorityPolicy(),
        stop_conditions=("debt <= 25000",),
    )

    result = ProgressEvaluator().evaluate(run_until, observation(debt=0))

    assert result.current_status is EvaluationStatus.COMPLETED
    assert result.complete
    assert not result.stop_condition_met


def adapter_validation(cost: float = 100.0, valid: bool = True) -> ValidationResult:
    return ValidationResult(valid=valid, message="checked", estimated_cost=cost)


@pytest.mark.parametrize(
    ("constraint", "reason"),
    [
        (
            Constraint(
                type=ConstraintType.FORBIDDEN_ACTION,
                description="No housing.",
                parameters={"action": "build_housing"},
            ),
            "forbidden",
        ),
        (
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Only wait.",
                parameters={"actions": ["advance_time"]},
            ),
            "allowed set",
        ),
        (
            Constraint(
                type=ConstraintType.MINIMUM_RESERVE,
                description="Keep reserve.",
                parameters={"amount": 450},
            ),
            "minimum reserve",
        ),
        (
            Constraint(
                type=ConstraintType.RESOURCE_FLOOR,
                description="Keep infrastructure above 70.",
                parameters={"resource": "infrastructure", "floor": 70},
            ),
            "required floor",
        ),
        (
            Constraint(
                type=ConstraintType.MAXIMUM_SPEND,
                description="Spend at most 50.",
                parameters={"amount": 50},
            ),
            "maximum spend constraint",
        ),
    ],
)
def test_policy_constraint_rejections(constraint: Constraint, reason: str) -> None:
    result = PolicyEngine().evaluate(
        specification(constraints=(constraint,)),
        make_action("build_housing", units=1),
        observation(cash=500, infrastructure=60),
        Decimal(0),
        adapter_validation(),
    )
    assert not result.allowed
    assert reason in "; ".join(result.reasons)


def test_policy_spend_limits_and_approval() -> None:
    authority = AuthorityPolicy(
        maximum_single_spend=Decimal(50),
        maximum_total_spend=Decimal(150),
        approval_actions=("repair",),
    )
    engine = PolicyEngine()

    approval = engine.evaluate(
        specification(authority=authority),
        make_action("build_housing", units=1),
        observation(cash=500),
        Decimal(0),
        adapter_validation(100),
    )
    total_rejection = engine.evaluate(
        specification(authority=authority),
        make_action("build_housing", units=1),
        observation(cash=500),
        Decimal(100),
        adapter_validation(100),
    )
    named_approval = engine.evaluate(
        specification(authority=authority),
        make_action("repair", amount=1),
        observation(cash=500),
        Decimal(0),
        adapter_validation(10),
    )

    assert approval.allowed and approval.approval_required
    assert not total_rejection.allowed
    assert named_approval.approval_required


def test_adapter_validation_failure_propagates() -> None:
    result = PolicyEngine().evaluate(
        specification(),
        make_action("build_housing", units=1),
        observation(cash=500),
        Decimal(0),
        adapter_validation(valid=False),
    )
    assert not result.allowed
    assert "adapter validation failed" in result.reasons[0]
