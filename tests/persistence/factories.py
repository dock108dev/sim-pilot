"""Deterministic records shared by persistence tests."""

from datetime import UTC, datetime, timedelta
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
from sim_pilot.persistence import (
    ApprovalRecord,
    CheckpointMetadata,
    EventRecord,
    SimulationCheckpoint,
    TaskRecord,
)
from sim_pilot.runtime.models import (
    ApprovalRequest,
    ApprovalStatus,
    RuntimeEvent,
    RuntimeEventType,
)

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TASK_ID = UUID("10000000-0000-0000-0000-000000000001")


def task_record(
    *,
    task_id: UUID = TASK_ID,
    status: TaskStatus = TaskStatus.PENDING,
    sequence: int = 0,
    updated_at: datetime = NOW,
    cancel_requested: bool = False,
) -> TaskRecord:
    task = Task(
        id=task_id,
        status=status,
        specification=TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach target cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            authority=AuthorityPolicy(),
        ),
        sequence=sequence,
        total_spend=Decimal("125.50") if sequence else Decimal(0),
        created_at=NOW,
        updated_at=updated_at,
    )
    return TaskRecord(task=task, cancel_requested=cancel_requested)


def action(action_type: str = "advance_time") -> Action:
    return Action(
        type=action_type,
        parameters={"ticks": 1} if action_type == "advance_time" else {"amount": 1},
        expected_effect="Change deterministic simulation state.",
        estimated_cost=Decimal(0),
    )


def event_record(sequence: int, *, task_id: UUID = TASK_ID) -> EventRecord:
    return EventRecord(
        id=UUID(f"20000000-0000-0000-0000-{sequence:012d}"),
        event=RuntimeEvent(
            task_id=task_id,
            sequence=sequence,
            event_type=RuntimeEventType.OBSERVATION_RECORDED,
            timestamp=NOW + timedelta(seconds=sequence),
            payload={"sequence": sequence},
        ),
    )


def approval_record(
    *,
    identifier: int = 1,
    action_type: str = "advance_time",
    status: ApprovalStatus = ApprovalStatus.PENDING,
) -> ApprovalRecord:
    resolved_at = None if status is ApprovalStatus.PENDING else NOW + timedelta(minutes=identifier)
    return ApprovalRecord(
        approval=ApprovalRequest(
            id=UUID(f"30000000-0000-0000-0000-{identifier:012d}"),
            task_id=TASK_ID,
            action=action(action_type),
            status=status,
            created_at=NOW + timedelta(seconds=identifier),
            resolved_at=resolved_at,
        ),
        reason=None if status is ApprovalStatus.PENDING else f"approval {status.value}",
    )


def checkpoint(
    runtime_sequence: int,
    *,
    simulation_schema_version: int = 1,
) -> SimulationCheckpoint:
    return SimulationCheckpoint(
        metadata=CheckpointMetadata(
            id=UUID(f"40000000-0000-0000-0000-{runtime_sequence:012d}"),
            task_id=TASK_ID,
            runtime_sequence=runtime_sequence,
            simulation_tick=runtime_sequence * 2,
            simulation_schema_version=simulation_schema_version,
            created_at=NOW + timedelta(seconds=runtime_sequence),
        ),
        state={
            "schema_version": simulation_schema_version,
            "tick": runtime_sequence * 2,
            "cash": 500_000.0 + runtime_sequence,
            "paused": False,
        },
    )
