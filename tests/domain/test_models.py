"""Tests for constructing and serializing domain models."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from sim_pilot.domain import (
    Action,
    AdapterId,
    AuthorityPolicy,
    Constraint,
    ConstraintType,
    Decision,
    DecisionType,
    ExecutionResult,
    Objective,
    ObjectiveType,
    Observation,
    Task,
    TaskSpecification,
    TaskStatus,
)


def make_action() -> Action:
    return Action(
        type="build_station",
        parameters={"city": "Aldford", "platforms": 2},
        expected_effect="A station exists in Aldford.",
        estimated_cost=Decimal("250000"),
    )


def make_specification() -> TaskSpecification:
    return TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach one million in cash.",
            parameters={"resource": "cash", "target": 1_000_000},
        ),
        constraints=(
            Constraint(
                type=ConstraintType.FORBIDDEN_ACTION,
                description="Do not take loans.",
                parameters={"action": "take_loan"},
            ),
        ),
        authority=AuthorityPolicy(
            maximum_single_spend=Decimal("300000"),
            maximum_total_spend=Decimal("750000"),
            approval_actions=("demolish",),
            forbidden_actions=("take_loan",),
        ),
        notifications=("Notify when complete.",),
        stop_conditions=("Stop if infrastructure health is below 40%.",),
    )


def make_task() -> Task:
    created_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    return Task(
        id=uuid4(),
        status=TaskStatus.PENDING,
        specification=make_specification(),
        sequence=0,
        total_spend=Decimal(0),
        created_at=created_at,
        updated_at=created_at,
    )


def test_constructs_all_domain_models() -> None:
    task = make_task()
    observation = Observation(
        sequence=1,
        timestamp=datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
        tick=7,
        summary="Cash increased during the last tick.",
        state={"cash": 850000, "paused": False},
    )
    action = make_action()
    decision = Decision(
        type=DecisionType.EXECUTE,
        reason="The station advances the objective within authority limits.",
        action=action,
    )
    result = ExecutionResult(
        success=True,
        state_changed=True,
        cost=250000.0,
        message="Station constructed.",
    )

    assert task.specification.objective.type is ObjectiveType.REACH_RESOURCE
    assert observation.state["cash"] == 850000
    assert decision.action == action
    assert observation.tick == 7
    assert result.success is True


def test_task_round_trips_through_json() -> None:
    task = make_task()

    restored = Task.model_validate_json(task.model_dump_json())

    assert restored == task
    assert isinstance(restored.id, UUID)
    assert restored.total_spend == Decimal(0)
    assert restored.schema_version == 1
    assert restored.specification.schema_version == 1


def test_cycle_models_round_trip_through_json() -> None:
    observation = Observation(
        sequence=2,
        timestamp=datetime(2026, 7, 16, 12, 2, tzinfo=UTC),
        tick=8,
        summary="A station is available.",
        state={"station_count": 1},
    )
    action = make_action()
    decision = Decision(
        type=DecisionType.APPROVAL_REQUIRED,
        reason="Station construction requires approval.",
        action=action,
    )
    result = ExecutionResult(
        success=False,
        state_changed=False,
        cost=0.0,
        message="Action was not executed.",
    )

    assert Observation.model_validate_json(observation.model_dump_json()) == observation
    assert Action.model_validate_json(action.model_dump_json()) == action
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    assert ExecutionResult.model_validate_json(result.model_dump_json()) == result


def test_schema_version_is_serialized_on_domain_models() -> None:
    action = make_action()

    assert action.model_dump()["schema_version"] == 1
    assert action.model_validate_json(action.model_dump_json()).schema_version == 1


def test_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Objective(
            schema_version=0,
            type=ObjectiveType.RUN_UNTIL,
            description="Run until the target tick.",
        )


def test_task_specification_rejects_unknown_adapter_type() -> None:
    payload = make_specification().model_dump(mode="json")
    payload["adapter_type"] = "legacy-or-unknown"

    with pytest.raises(ValidationError, match="adapter_type"):
        TaskSpecification.model_validate(payload)


def test_task_specification_accepts_registered_discovery_only_adapter() -> None:
    specification = make_specification().model_copy(update={"adapter_type": AdapterId.SOFTWARE_INC})

    restored = TaskSpecification.model_validate_json(specification.model_dump_json())

    assert restored.adapter_type is AdapterId.SOFTWARE_INC


def test_observation_is_immutable() -> None:
    observation = Observation(
        sequence=0,
        timestamp=datetime.now(UTC),
        tick=0,
        summary="Initial state.",
        state={"cash": 1000},
    )

    with pytest.raises(ValidationError, match="frozen"):
        observation.sequence = 1


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: AuthorityPolicy(
                maximum_single_spend=Decimal("200"),
                maximum_total_spend=Decimal("100"),
            ),
            "maximum_single_spend",
        ),
        (
            lambda: Decision(
                type=DecisionType.EXECUTE,
                reason="Advance the task.",
            ),
            "action is required",
        ),
        (
            lambda: Action(
                type="wait",
                expected_effect="Time advances.",
                estimated_cost=Decimal("-1"),
            ),
            "greater than or equal to 0",
        ),
        (
            lambda: Observation(
                sequence=-1,
                timestamp=datetime.now(UTC),
                tick=0,
                summary="Invalid sequence.",
                state={},
            ),
            "greater than or equal to 0",
        ),
        (
            lambda: Observation(
                sequence=0,
                timestamp=datetime.now(UTC),
                tick=-1,
                summary="Invalid tick.",
                state={},
            ),
            "greater than or equal to 0",
        ),
        (
            lambda: ExecutionResult(
                success=True,
                state_changed=True,
                cost=-1.0,
                message="Invalid cost.",
            ),
            "greater than or equal to 0",
        ),
        (
            lambda: Task(
                id=uuid4(),
                status=TaskStatus.PENDING,
                specification=make_specification(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC) - timedelta(days=1),
            ),
            "updated_at",
        ),
    ],
)
def test_rejects_invalid_domain_input(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        factory()


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Objective.model_validate(
            {
                "type": ObjectiveType.RUN_UNTIL,
                "description": "Run until the next year.",
                "parameters": {},
                "unexpected": True,
            }
        )
