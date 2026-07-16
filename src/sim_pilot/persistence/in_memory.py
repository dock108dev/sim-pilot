"""Transactional in-memory implementations of all repository contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import TracebackType
from uuid import UUID

from sim_pilot.persistence.errors import (
    DuplicateRecordError,
    RecordNotFoundError,
    SequenceConflictError,
    StaleUpdateError,
    TransactionError,
    UnsupportedSchemaVersionError,
)
from sim_pilot.persistence.models import (
    ApprovalRecord,
    EventRecord,
    SimulationCheckpoint,
    TaskRecord,
)
from sim_pilot.runtime.models import ApprovalStatus


@dataclass
class InMemoryPersistenceState:
    """Shared committed data for one or more in-memory units of work."""

    tasks: dict[UUID, TaskRecord] = field(default_factory=lambda: dict[UUID, TaskRecord]())
    events: dict[UUID, list[EventRecord]] = field(
        default_factory=lambda: dict[UUID, list[EventRecord]]()
    )
    approvals: dict[UUID, ApprovalRecord] = field(
        default_factory=lambda: dict[UUID, ApprovalRecord]()
    )
    checkpoints: dict[UUID, list[SimulationCheckpoint]] = field(
        default_factory=lambda: dict[UUID, list[SimulationCheckpoint]]()
    )

    def replace_with(self, other: InMemoryPersistenceState) -> None:
        self.tasks = other.tasks
        self.events = other.events
        self.approvals = other.approvals
        self.checkpoints = other.checkpoints


class InMemoryTaskRepository:
    def __init__(self, state: InMemoryPersistenceState) -> None:
        self._state = state

    def create(self, record: TaskRecord) -> None:
        task_id = record.task.id
        if task_id in self._state.tasks:
            raise DuplicateRecordError(f"task {task_id} already exists")
        self._state.tasks[task_id] = record

    def get(self, task_id: UUID) -> TaskRecord:
        try:
            return self._state.tasks[task_id]
        except KeyError as error:
            raise RecordNotFoundError(f"task {task_id} was not found") from error

    def update(self, record: TaskRecord) -> None:
        task_id = record.task.id
        current = self.get(task_id)
        if (
            record.task.sequence < current.task.sequence
            or record.task.updated_at < current.task.updated_at
        ):
            raise StaleUpdateError(f"task {task_id} update is stale")
        self._state.tasks[task_id] = record

    def list(self) -> tuple[TaskRecord, ...]:
        return tuple(
            sorted(
                self._state.tasks.values(),
                key=lambda record: (record.task.created_at, str(record.task.id)),
            )
        )


class InMemoryEventRepository:
    def __init__(self, state: InMemoryPersistenceState) -> None:
        self._state = state

    def append(self, record: EventRecord) -> None:
        self.append_many((record,))

    def append_many(self, records: tuple[EventRecord, ...]) -> None:
        expected_by_task: dict[UUID, int] = {}
        identifiers = {event.id for stream in self._state.events.values() for event in stream}
        pending_identifiers: set[UUID] = set()

        for record in records:
            task_id = record.event.task_id
            if task_id not in self._state.tasks:
                raise RecordNotFoundError(f"task {task_id} was not found")
            if record.id in identifiers or record.id in pending_identifiers:
                raise DuplicateRecordError(f"event {record.id} already exists")
            stream = self._state.events.get(task_id, [])
            expected = expected_by_task.get(task_id, len(stream) + 1)
            if record.event.sequence != expected:
                raise SequenceConflictError(
                    f"expected event sequence {expected}, received {record.event.sequence}"
                )
            expected_by_task[task_id] = expected + 1
            pending_identifiers.add(record.id)

        for record in records:
            self._state.events.setdefault(record.event.task_id, []).append(record)

    def list_for_task(self, task_id: UUID) -> tuple[EventRecord, ...]:
        return tuple(self._state.events.get(task_id, ()))

    def latest(self, task_id: UUID) -> EventRecord | None:
        stream = self._state.events.get(task_id)
        return stream[-1] if stream else None

    def get_by_sequence(self, task_id: UUID, sequence: int) -> EventRecord:
        stream = self._state.events.get(task_id, ())
        if sequence < 1 or sequence > len(stream):
            raise RecordNotFoundError(f"event {task_id}/{sequence} was not found")
        return stream[sequence - 1]


class InMemoryApprovalRepository:
    def __init__(self, state: InMemoryPersistenceState) -> None:
        self._state = state

    def create(self, record: ApprovalRecord) -> None:
        approval = record.approval
        if approval.task_id not in self._state.tasks:
            raise RecordNotFoundError(f"task {approval.task_id} was not found")
        if approval.id in self._state.approvals:
            raise DuplicateRecordError(f"approval {approval.id} already exists")
        if approval.status is ApprovalStatus.PENDING:
            action_json = approval.action.model_dump_json()
            duplicate = any(
                existing.approval.task_id == approval.task_id
                and existing.approval.status is ApprovalStatus.PENDING
                and existing.approval.action.model_dump_json() == action_json
                for existing in self._state.approvals.values()
            )
            if duplicate:
                raise DuplicateRecordError("a pending approval already exists for this action")
        self._state.approvals[approval.id] = record

    def get(self, approval_id: UUID) -> ApprovalRecord:
        try:
            return self._state.approvals[approval_id]
        except KeyError as error:
            raise RecordNotFoundError(f"approval {approval_id} was not found") from error

    def get_pending_for_task(self, task_id: UUID) -> ApprovalRecord | None:
        pending = [
            record
            for record in self._state.approvals.values()
            if record.approval.task_id == task_id
            and record.approval.status is ApprovalStatus.PENDING
        ]
        pending.sort(key=lambda record: (record.approval.created_at, str(record.approval.id)))
        return pending[0] if pending else None

    def update(self, record: ApprovalRecord) -> None:
        approval_id = record.approval.id
        current = self.get(approval_id)
        if current.approval.status is not ApprovalStatus.PENDING:
            raise StaleUpdateError(f"approval {approval_id} is already resolved")
        if record.approval.created_at != current.approval.created_at:
            raise StaleUpdateError(f"approval {approval_id} creation data is immutable")
        self._state.approvals[approval_id] = record

    def list_for_task(self, task_id: UUID) -> tuple[ApprovalRecord, ...]:
        records = [
            record
            for record in self._state.approvals.values()
            if record.approval.task_id == task_id
        ]
        return tuple(
            sorted(
                records, key=lambda record: (record.approval.created_at, str(record.approval.id))
            )
        )


class InMemorySimulationRepository:
    def __init__(self, state: InMemoryPersistenceState) -> None:
        self._state = state

    def save(self, checkpoint: SimulationCheckpoint) -> None:
        task_id = checkpoint.metadata.task_id
        if checkpoint.metadata.simulation_schema_version != 1:
            raise UnsupportedSchemaVersionError(
                "simulation checkpoint schema version is unsupported"
            )
        if task_id not in self._state.tasks:
            raise RecordNotFoundError(f"task {task_id} was not found")
        stream = self._state.checkpoints.setdefault(task_id, [])
        latest_sequence = stream[-1].metadata.runtime_sequence if stream else -1
        if checkpoint.metadata.runtime_sequence <= latest_sequence:
            raise StaleUpdateError(
                f"checkpoint sequence {checkpoint.metadata.runtime_sequence} is not newer than "
                f"{latest_sequence}"
            )
        if any(
            existing.metadata.id == checkpoint.metadata.id
            for checkpoints in self._state.checkpoints.values()
            for existing in checkpoints
        ):
            raise DuplicateRecordError(f"checkpoint {checkpoint.metadata.id} already exists")
        stream.append(checkpoint)

    def latest(self, task_id: UUID) -> SimulationCheckpoint | None:
        stream = self._state.checkpoints.get(task_id)
        return stream[-1] if stream else None

    def get_by_runtime_sequence(self, task_id: UUID, runtime_sequence: int) -> SimulationCheckpoint:
        for checkpoint in self._state.checkpoints.get(task_id, ()):
            if checkpoint.metadata.runtime_sequence == runtime_sequence:
                return checkpoint
        raise RecordNotFoundError(f"checkpoint {task_id}/{runtime_sequence} was not found")


class InMemoryUnitOfWork:
    """Copy-on-begin transaction boundary over shared in-memory state."""

    def __init__(self, state: InMemoryPersistenceState | None = None) -> None:
        self._state = state or InMemoryPersistenceState()
        self._snapshot: InMemoryPersistenceState | None = None
        self.tasks = InMemoryTaskRepository(self._state)
        self.events = InMemoryEventRepository(self._state)
        self.approvals = InMemoryApprovalRepository(self._state)
        self.simulations = InMemorySimulationRepository(self._state)

    def begin(self) -> None:
        if self._snapshot is not None:
            raise TransactionError("unit of work is already active")
        self._snapshot = deepcopy(self._state)

    def commit(self) -> None:
        if self._snapshot is None:
            raise TransactionError("unit of work is not active")
        self._snapshot = None

    def rollback(self) -> None:
        if self._snapshot is None:
            raise TransactionError("unit of work is not active")
        self._state.replace_with(self._snapshot)
        self._snapshot = None

    def __enter__(self) -> InMemoryUnitOfWork:
        self.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False
