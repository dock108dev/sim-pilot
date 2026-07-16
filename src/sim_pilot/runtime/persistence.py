"""Atomic runtime persistence operations over storage-independent repositories."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import Task
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import (
    ApprovalRecord,
    EventRecord,
    PersistenceError,
    SimulationCheckpoint,
    TaskRecord,
    UnitOfWork,
)
from sim_pilot.persistence.models import CheckpointMetadata
from sim_pilot.runtime.errors import DurablePersistenceError
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType, RuntimeSafeguardState

type UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class EventDraft:
    event_type: RuntimeEventType
    payload: dict[str, JsonValue]


@dataclass(frozen=True)
class IterationCommit:
    task_record: TaskRecord
    events: tuple[RuntimeEvent, ...]
    checkpoint: SimulationCheckpoint | None


class RuntimePersistence:
    """Build and commit complete runtime iterations atomically."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    @property
    def unit_of_work_factory(self) -> UnitOfWorkFactory:
        return self._factory

    def create_task(self, task: Task) -> TaskRecord:
        event = RuntimeEvent(
            task_id=task.id,
            sequence=1,
            event_type=RuntimeEventType.TASK_CREATED,
            timestamp=task.created_at,
            payload={},
        )
        stored_task = task.model_copy(update={"sequence": 1})
        record = TaskRecord(task=stored_task)
        try:
            with self._factory() as uow:
                uow.tasks.create(record)
                uow.events.append(self._event_record(event))
        except PersistenceError as error:
            raise DurablePersistenceError(f"task creation was not persisted: {error}") from error
        return record

    def commit_iteration(
        self,
        current: TaskRecord,
        *,
        task: Task,
        runtime_state: RuntimeSafeguardState,
        event_drafts: tuple[EventDraft, ...],
        cancel_requested: bool | None = None,
        approval_create: ApprovalRecord | None = None,
        approval_update: ApprovalRecord | None = None,
        adapter_snapshot: AdapterSnapshot | None = None,
    ) -> IterationCommit:
        if not event_drafts:
            msg = "an atomic runtime iteration must contain at least one event"
            raise ValueError(msg)
        now = datetime.now(UTC)
        events = tuple(
            RuntimeEvent(
                task_id=task.id,
                sequence=current.task.sequence + offset,
                event_type=draft.event_type,
                timestamp=now,
                payload=draft.payload,
            )
            for offset, draft in enumerate(event_drafts, start=1)
        )
        updated_task = task.model_copy(update={"sequence": events[-1].sequence, "updated_at": now})
        updated_record = TaskRecord(
            task=updated_task,
            cancel_requested=(
                current.cancel_requested if cancel_requested is None else cancel_requested
            ),
            runtime_state=runtime_state,
        )
        checkpoint = (
            None
            if adapter_snapshot is None
            else self._checkpoint(updated_task.id, events[-1].sequence, now, adapter_snapshot)
        )
        try:
            with self._factory() as uow:
                uow.tasks.update(updated_record)
                uow.events.append_many(tuple(self._event_record(event) for event in events))
                if approval_create is not None:
                    uow.approvals.create(approval_create)
                if approval_update is not None:
                    uow.approvals.update(approval_update)
                if checkpoint is not None:
                    uow.simulations.save(checkpoint)
        except PersistenceError as error:
            raise DurablePersistenceError(
                f"runtime iteration was not persisted: {error}"
            ) from error
        return IterationCommit(updated_record, events, checkpoint)

    def copy_checkpoint_for_terminal(
        self, checkpoint: SimulationCheckpoint | None
    ) -> AdapterSnapshot | None:
        if checkpoint is None:
            return None
        metadata = checkpoint.metadata
        return AdapterSnapshot(
            adapter_type=metadata.adapter_type,
            simulation_schema_version=metadata.simulation_schema_version,
            observation_sequence=metadata.adapter_observation_sequence,
            seed=metadata.adapter_seed,
            state=checkpoint.state,
        )

    @staticmethod
    def _event_record(event: RuntimeEvent) -> EventRecord:
        return EventRecord(
            id=uuid5(NAMESPACE_URL, f"sim-pilot:{event.task_id}:event:{event.sequence}"),
            event=event,
        )

    @staticmethod
    def _checkpoint(
        task_id: UUID,
        runtime_sequence: int,
        created_at: datetime,
        snapshot: AdapterSnapshot,
    ) -> SimulationCheckpoint:
        tick = snapshot.state.get("tick", 0)
        if isinstance(tick, bool) or not isinstance(tick, int):
            raise ValueError("adapter snapshot tick must be an integer")
        return SimulationCheckpoint(
            metadata=CheckpointMetadata(
                id=uuid5(
                    NAMESPACE_URL,
                    f"sim-pilot:{task_id}:checkpoint:{runtime_sequence}",
                ),
                task_id=task_id,
                runtime_sequence=runtime_sequence,
                simulation_tick=tick,
                simulation_schema_version=snapshot.simulation_schema_version,
                adapter_type=snapshot.adapter_type,
                adapter_schema_version=snapshot.schema_version,
                adapter_observation_sequence=snapshot.observation_sequence,
                adapter_seed=snapshot.seed,
                created_at=created_at,
            ),
            state=snapshot.state,
        )


class RepositoryEventView:
    """Read-only compatibility view used by existing Task 3 callers."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def list_events(self, task_id: UUID) -> tuple[RuntimeEvent, ...]:
        uow = self._factory()
        uow.begin()
        try:
            records = uow.events.list_for_task(task_id)
        finally:
            uow.rollback()
        return tuple(record.event for record in records)

    def latest(self, task_id: UUID) -> RuntimeEvent | None:
        uow = self._factory()
        uow.begin()
        try:
            record = uow.events.latest(task_id)
        finally:
            uow.rollback()
        return None if record is None else record.event
