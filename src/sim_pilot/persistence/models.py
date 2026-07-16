"""Strict storage-independent records used by persistence repositories."""

from datetime import timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sim_pilot.domain import Task
from sim_pilot.domain.models import JsonValue
from sim_pilot.runtime.models import ApprovalRequest, ApprovalStatus, RuntimeEvent


def _is_utc(value: AwareDatetime) -> bool:
    return value.utcoffset() == timedelta(0)


class PersistenceRecord(BaseModel):
    """Common strict and immutable durable-record contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class TaskRecord(PersistenceRecord):
    """Current task snapshot plus durable cancellation intent."""

    task: Task
    cancel_requested: bool = False

    @model_validator(mode="after")
    def validate_utc_timestamps(self) -> Self:
        if self.task.schema_version != self.schema_version:
            msg = "task schema version does not match its durable record"
            raise ValueError(msg)
        if not _is_utc(self.task.created_at) or not _is_utc(self.task.updated_at):
            msg = "task timestamps must be UTC"
            raise ValueError(msg)
        return self


class EventRecord(PersistenceRecord):
    """A stable durable identity around an immutable runtime event."""

    id: UUID
    event: RuntimeEvent

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if not _is_utc(self.event.timestamp):
            msg = "event timestamp must be UTC"
            raise ValueError(msg)
        return self


class ApprovalRecord(PersistenceRecord):
    """A durable approval request and its resolution state."""

    approval: ApprovalRequest
    reason: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        approval = self.approval
        if not _is_utc(approval.created_at):
            msg = "approval created_at must be UTC"
            raise ValueError(msg)
        if approval.resolved_at is not None and not _is_utc(approval.resolved_at):
            msg = "approval resolved_at must be UTC"
            raise ValueError(msg)
        if approval.status is ApprovalStatus.PENDING and approval.resolved_at is not None:
            msg = "pending approval cannot have resolved_at"
            raise ValueError(msg)
        if approval.status is not ApprovalStatus.PENDING and approval.resolved_at is None:
            msg = "resolved approval requires resolved_at"
            raise ValueError(msg)
        return self


class CheckpointMetadata(PersistenceRecord):
    """Version and ordering information for a simulation checkpoint."""

    id: UUID
    task_id: UUID
    runtime_sequence: int = Field(ge=0)
    simulation_tick: int = Field(ge=0)
    simulation_schema_version: int = Field(ge=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if not _is_utc(self.created_at):
            msg = "checkpoint created_at must be UTC"
            raise ValueError(msg)
        return self


class SimulationCheckpoint(PersistenceRecord):
    """A complete versioned reference-simulation state snapshot."""

    metadata: CheckpointMetadata
    state: dict[str, JsonValue]
