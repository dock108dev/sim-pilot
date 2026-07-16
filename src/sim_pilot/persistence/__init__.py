"""Storage-independent persistence contracts and in-memory implementations."""

from sim_pilot.persistence.errors import (
    DuplicateRecordError,
    InvalidPersistedPayloadError,
    PersistenceError,
    RecordNotFoundError,
    SequenceConflictError,
    StaleUpdateError,
    TransactionError,
    UnsupportedSchemaVersionError,
)
from sim_pilot.persistence.in_memory import InMemoryPersistenceState, InMemoryUnitOfWork
from sim_pilot.persistence.models import (
    ApprovalRecord,
    CheckpointMetadata,
    EventRecord,
    SimulationCheckpoint,
    TaskRecord,
)
from sim_pilot.persistence.repositories import (
    ApprovalRepository,
    EventRepository,
    SimulationRepository,
    TaskRepository,
)
from sim_pilot.persistence.unit_of_work import UnitOfWork

__all__ = [
    "ApprovalRecord",
    "ApprovalRepository",
    "CheckpointMetadata",
    "DuplicateRecordError",
    "EventRecord",
    "EventRepository",
    "InMemoryPersistenceState",
    "InMemoryUnitOfWork",
    "InvalidPersistedPayloadError",
    "PersistenceError",
    "RecordNotFoundError",
    "SequenceConflictError",
    "SimulationCheckpoint",
    "SimulationRepository",
    "StaleUpdateError",
    "TaskRecord",
    "TaskRepository",
    "TransactionError",
    "UnitOfWork",
    "UnsupportedSchemaVersionError",
]
