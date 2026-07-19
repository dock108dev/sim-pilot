"""Pure state and serialization helpers shared by runtime orchestration."""

import json
from typing import cast

from sim_pilot.adapters.base import (
    AdapterSnapshot,
    CheckpointableSimulationAdapter,
    SimulationAdapter,
)
from sim_pilot.domain import Action, Observation, Task, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import TaskRecord
from sim_pilot.runtime.errors import ReconstructionConsistencyError
from sim_pilot.runtime.lifecycle import transition
from sim_pilot.runtime.models import (
    RuntimeEventType,
    RuntimeOutcome,
    RuntimeSafeguardState,
)
from sim_pilot.runtime.persistence import EventDraft
from sim_pilot.runtime.reconstruction import ReconstructedRuntimeContext


def task_record(context: ReconstructedRuntimeContext) -> TaskRecord:
    return TaskRecord(
        task=context.task,
        cancel_requested=context.cancel_requested,
        runtime_state=context.runtime_state,
    )


def with_status(task: Task, status: TaskStatus) -> Task:
    transition(task.status, status)
    return task.model_copy(update={"status": status})


def force_failed(task: Task) -> Task:
    if task.status is TaskStatus.PENDING:
        transition(task.status, TaskStatus.RUNNING)
    return task.model_copy(update={"status": TaskStatus.FAILED})


def observation_draft(observation: Observation) -> EventDraft:
    return EventDraft(
        RuntimeEventType.OBSERVATION_RECORDED,
        cast("dict[str, JsonValue]", observation.model_dump(mode="json")),
    )


def adapter_snapshot(adapter: SimulationAdapter, observation: Observation) -> AdapterSnapshot:
    if isinstance(adapter, CheckpointableSimulationAdapter):
        return adapter.snapshot()
    schema_version = observation.state.get("schema_version", 1)
    if not isinstance(schema_version, int):
        schema_version = 1
    return AdapterSnapshot(
        adapter_type=str(
            getattr(
                adapter,
                "adapter_type",
                f"{type(adapter).__module__}.{type(adapter).__qualname__}",
            )
        ),
        simulation_schema_version=schema_version,
        observation_sequence=observation.sequence,
        seed="0",
        state=cast("dict[str, JsonValue]", observation.state),
    )


def action_state_fingerprint(action: Action, observation: Observation) -> str:
    return json.dumps(
        {
            "action": action.model_dump(mode="json"),
            "state": observation.state,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_restored_adapter(
    adapter: SimulationAdapter, context: ReconstructedRuntimeContext
) -> None:
    if not isinstance(adapter, CheckpointableSimulationAdapter):
        return
    if adapter.snapshot() != context.adapter_snapshot():
        raise ReconstructionConsistencyError(
            "restored adapter does not match the latest durable checkpoint"
        )


def is_terminal(status: TaskStatus) -> bool:
    return status in {
        TaskStatus.COMPLETED,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }


def runtime_outcome(
    task: Task,
    runtime_state: RuntimeSafeguardState,
    reason: str | None,
    context: ReconstructedRuntimeContext | None = None,
) -> RuntimeOutcome:
    pending = None
    if context is not None and context.pending_approval is not None:
        pending = context.pending_approval.approval
    return RuntimeOutcome(
        task_id=task.id,
        status=task.status,
        total_spend=float(task.total_spend),
        iterations=runtime_state.iterations,
        reason=reason,
        pending_approval=pending,
    )
