"""Typed reconstruction and consistency validation for persisted runtime state."""

import json
from uuid import UUID

from pydantic import ConfigDict

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import Observation, Task, TaskStatus
from sim_pilot.persistence import ApprovalRecord, SimulationCheckpoint, TaskRecord
from sim_pilot.runtime.errors import ReconstructionConsistencyError
from sim_pilot.runtime.models import (
    ApprovalStatus,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeModel,
    RuntimeSafeguardState,
)
from sim_pilot.runtime.persistence import UnitOfWorkFactory

TERMINAL_EVENT = {
    TaskStatus.COMPLETED: RuntimeEventType.TASK_COMPLETED,
    TaskStatus.BLOCKED: RuntimeEventType.TASK_BLOCKED,
    TaskStatus.FAILED: RuntimeEventType.TASK_FAILED,
    TaskStatus.CANCELLED: RuntimeEventType.TASK_CANCELLED,
}


class ReconstructedRuntimeContext(RuntimeModel):
    """Validated state sufficient to reopen a persisted task."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, arbitrary_types_allowed=True
    )

    task: Task
    cancel_requested: bool
    runtime_state: RuntimeSafeguardState
    events: tuple[RuntimeEvent, ...]
    approvals: tuple[ApprovalRecord, ...]
    checkpoint: SimulationCheckpoint | None
    observation: Observation | None
    reason: str | None = None

    def adapter_snapshot(self) -> AdapterSnapshot:
        checkpoint = self.checkpoint
        if checkpoint is None:
            raise ReconstructionConsistencyError("task has no simulation checkpoint")
        metadata = checkpoint.metadata
        return AdapterSnapshot(
            adapter_type=metadata.adapter_type,
            simulation_schema_version=metadata.simulation_schema_version,
            observation_sequence=(
                metadata.adapter_observation_sequence
                if self.observation is None
                else self.observation.sequence
            ),
            seed=metadata.adapter_seed,
            state=checkpoint.state,
        )

    @property
    def pending_approval(self) -> ApprovalRecord | None:
        return next(
            (
                record
                for record in self.approvals
                if record.approval.status is ApprovalStatus.PENDING
            ),
            None,
        )


class RuntimeReconstructor:
    """Load all durable records and reject inconsistent combinations."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def load(self, task_id: UUID) -> ReconstructedRuntimeContext:
        uow = self._factory()
        uow.begin()
        try:
            task_record = uow.tasks.get(task_id)
            event_records = uow.events.list_for_task(task_id)
            approvals = uow.approvals.list_for_task(task_id)
            checkpoint = uow.simulations.latest(task_id)
        finally:
            uow.rollback()
        events = tuple(record.event for record in event_records)
        observation = self._latest_observation(events)
        self._validate(task_record, events, approvals, checkpoint, observation)
        reason_value = events[-1].payload.get("reason") if events else None
        reason = reason_value if isinstance(reason_value, str) else None
        return ReconstructedRuntimeContext(
            task=task_record.task,
            cancel_requested=task_record.cancel_requested,
            runtime_state=task_record.runtime_state,
            events=events,
            approvals=approvals,
            checkpoint=checkpoint,
            observation=observation,
            reason=reason,
        )

    @staticmethod
    def _latest_observation(events: tuple[RuntimeEvent, ...]) -> Observation | None:
        for event in reversed(events):
            if event.event_type is RuntimeEventType.OBSERVATION_RECORDED:
                try:
                    return Observation.model_validate_json(json.dumps(event.payload))
                except ValueError as error:
                    raise ReconstructionConsistencyError(
                        f"persisted observation is invalid: {error}"
                    ) from error
        return None

    def _validate(
        self,
        task_record: TaskRecord,
        events: tuple[RuntimeEvent, ...],
        approvals: tuple[ApprovalRecord, ...],
        checkpoint: SimulationCheckpoint | None,
        observation: Observation | None,
    ) -> None:
        task = task_record.task
        if not events or events[0].event_type is not RuntimeEventType.TASK_CREATED:
            self._fail("event history must begin with TaskCreated")
        if any(event.task_id != task.id for event in events):
            self._fail("event history contains another task")
        if [event.sequence for event in events] != list(range(1, len(events) + 1)):
            self._fail("event history is not contiguous")
        if task.sequence != events[-1].sequence:
            self._fail("task current sequence does not match latest event")
        if (
            task.status in TERMINAL_EVENT
            and events[-1].event_type is not TERMINAL_EVENT[task.status]
        ):
            self._fail("terminal task status does not match latest event")
        if task_record.cancel_requested != (task.status is TaskStatus.CANCELLED):
            self._fail("cancellation flag and task status disagree")

        pending = tuple(
            record for record in approvals if record.approval.status is ApprovalStatus.PENDING
        )
        state = task_record.runtime_state
        has_approved_once = state.approved_once_action is not None
        if (state.approved_approval_id is None) != (not has_approved_once):
            self._fail("approved-once action identity is incomplete")
        if pending and task.status is not TaskStatus.WAITING_FOR_APPROVAL:
            self._fail("pending approval requires waiting_for_approval status")
        if task.status is TaskStatus.WAITING_FOR_APPROVAL and not pending and not has_approved_once:
            self._fail("waiting task has neither pending nor granted approval")
        if task.status in TERMINAL_EVENT and pending:
            self._fail("terminal task cannot retain a pending approval")
        if has_approved_once:
            matching = [
                record
                for record in approvals
                if record.approval.id == state.approved_approval_id
                and record.approval.status is ApprovalStatus.APPROVED
                and record.approval.action == state.approved_once_action
            ]
            if len(matching) != 1:
                self._fail("approved-once authorization does not match approval history")

        requires_checkpoint = task.status in {
            TaskStatus.RUNNING,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
        } or (task.status is TaskStatus.FAILED and observation is not None)
        if requires_checkpoint and checkpoint is None:
            self._fail("initialized task has no simulation checkpoint")
        if checkpoint is not None:
            if checkpoint.metadata.task_id != task.id:
                self._fail("checkpoint belongs to another task")
            if checkpoint.metadata.runtime_sequence > task.sequence:
                self._fail("checkpoint is ahead of task sequence")
            if checkpoint.metadata.adapter_schema_version != 1:
                self._fail("adapter checkpoint schema version is unsupported")
            state_schema = checkpoint.state.get("schema_version")
            if (
                state_schema is not None
                and state_schema != checkpoint.metadata.simulation_schema_version
            ):
                self._fail("checkpoint simulation schema versions disagree")
            state_tick = checkpoint.state.get("tick")
            if state_tick is not None and state_tick != checkpoint.metadata.simulation_tick:
                self._fail("checkpoint tick does not match serialized state")
            if observation is None:
                self._fail("checkpoint has no corresponding observation")
            if observation is not None:
                if (
                    observation.state != checkpoint.state
                    or observation.tick != checkpoint.metadata.simulation_tick
                ):
                    self._fail("latest observation and checkpoint state disagree")
                if observation.sequence < checkpoint.metadata.adapter_observation_sequence:
                    self._fail("adapter observation sequence is behind checkpoint")

    @staticmethod
    def _fail(message: str) -> None:
        raise ReconstructionConsistencyError(message)
