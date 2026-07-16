"""Shared deterministic runtime test builders."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Objective,
    ObjectiveType,
    Task,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.domain.models import JsonValue


def make_action(type_: str, **parameters: JsonValue) -> Action:
    return Action(
        type=type_,
        parameters=parameters,
        expected_effect=f"Execute {type_} deterministically.",
        estimated_cost=Decimal(0),
    )


def make_task(
    *,
    target: float = 520_000,
    specification: TaskSpecification | None = None,
) -> Task:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    spec = specification or TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach the cash target.",
            parameters={"resource": "cash", "target": target},
        ),
        authority=AuthorityPolicy(),
    )
    return Task(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        status=TaskStatus.PENDING,
        specification=spec,
        created_at=now,
        updated_at=now,
    )
