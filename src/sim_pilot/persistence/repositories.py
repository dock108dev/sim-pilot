"""Storage-independent repository interfaces consumed by later runtime work."""

from typing import Protocol
from uuid import UUID

from sim_pilot.persistence.models import (
    ApprovalRecord,
    EventRecord,
    SimulationCheckpoint,
    TaskRecord,
)


class TaskRepository(Protocol):
    """Store the latest durable snapshot for each task.

    Duplicate creates raise ``DuplicateRecordError``; missing reads and updates raise
    ``RecordNotFoundError``; an update older than the stored snapshot raises
    ``StaleUpdateError``.
    """

    def create(self, record: TaskRecord) -> None: ...

    def get(self, task_id: UUID) -> TaskRecord: ...

    def update(self, record: TaskRecord) -> None: ...

    def list(self) -> tuple[TaskRecord, ...]: ...


class EventRepository(Protocol):
    """Store immutable, strictly sequenced task event streams."""

    def append(self, record: EventRecord) -> None: ...

    def append_many(self, records: tuple[EventRecord, ...]) -> None: ...

    def list_for_task(self, task_id: UUID) -> tuple[EventRecord, ...]: ...

    def latest(self, task_id: UUID) -> EventRecord | None: ...

    def get_by_sequence(self, task_id: UUID, sequence: int) -> EventRecord: ...


class ApprovalRepository(Protocol):
    """Store approval requests and ordered resolution history."""

    def create(self, record: ApprovalRecord) -> None: ...

    def get(self, approval_id: UUID) -> ApprovalRecord: ...

    def get_pending_for_task(self, task_id: UUID) -> ApprovalRecord | None: ...

    def update(self, record: ApprovalRecord) -> None: ...

    def list_for_task(self, task_id: UUID) -> tuple[ApprovalRecord, ...]: ...


class SimulationRepository(Protocol):
    """Store immutable, monotonically ordered simulation checkpoints."""

    def save(self, checkpoint: SimulationCheckpoint) -> None: ...

    def latest(self, task_id: UUID) -> SimulationCheckpoint | None: ...

    def get_by_runtime_sequence(
        self, task_id: UUID, runtime_sequence: int
    ) -> SimulationCheckpoint: ...
