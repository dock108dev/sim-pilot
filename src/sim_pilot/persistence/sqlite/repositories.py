"""SQLite-backed repository implementations using one caller-owned transaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql import Executable

from sim_pilot.domain import Action, Task, TaskSpecification, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence.errors import (
    DuplicateRecordError,
    InvalidPersistedPayloadError,
    RecordNotFoundError,
    SequenceConflictError,
    StaleUpdateError,
    TransactionError,
    UnsupportedSchemaVersionError,
)
from sim_pilot.persistence.models import (
    ApprovalRecord,
    CheckpointMetadata,
    EventRecord,
    SimulationCheckpoint,
    TaskRecord,
)
from sim_pilot.persistence.sqlite.schema import (
    approvals,
    events,
    simulation_checkpoints,
    tasks,
)
from sim_pilot.runtime.models import (
    ApprovalRequest,
    ApprovalStatus,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeSafeguardState,
)

RowData = dict[str, Any]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("persisted timestamp is not text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("persisted timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _supported_schema(row: RowData) -> None:
    version = row.get("schema_version")
    if version != 1:
        raise UnsupportedSchemaVersionError(f"persisted schema version {version!r} is unsupported")


def _payload_error(record_type: str, error: Exception) -> InvalidPersistedPayloadError:
    return InvalidPersistedPayloadError(f"invalid persisted {record_type}: {error}")


def _write_error(error: SQLAlchemyError, record_type: str) -> Exception:
    if isinstance(error, IntegrityError):
        message = str(error.orig)
        if "FOREIGN KEY" in message:
            return RecordNotFoundError(f"associated task for {record_type} was not found")
        if "UNIQUE" in message:
            return DuplicateRecordError(f"duplicate {record_type}")
    return TransactionError(f"could not persist {record_type}: {error}")


def _read(connection: Connection, statement: Executable) -> CursorResult[Any]:
    try:
        return connection.execute(statement)
    except SQLAlchemyError as error:
        raise TransactionError(f"could not read persisted data: {error}") from error


class SQLiteTaskRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, record: TaskRecord) -> None:
        try:
            self._connection.execute(insert(tasks).values(**self._values(record)))
        except SQLAlchemyError as error:
            raise _write_error(error, "task") from error

    def get(self, task_id: UUID) -> TaskRecord:
        row = (
            _read(self._connection, select(tasks).where(tasks.c.id == str(task_id)))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecordNotFoundError(f"task {task_id} was not found")
        return self._record(dict(row))

    def update(self, record: TaskRecord) -> None:
        current = self.get(record.task.id)
        if (
            record.task.sequence < current.task.sequence
            or record.task.updated_at < current.task.updated_at
        ):
            raise StaleUpdateError(f"task {record.task.id} update is stale")
        try:
            self._connection.execute(
                update(tasks)
                .where(tasks.c.id == str(record.task.id))
                .values(**self._values(record))
            )
        except SQLAlchemyError as error:
            raise _write_error(error, "task") from error

    def list(self) -> tuple[TaskRecord, ...]:
        rows = _read(
            self._connection, select(tasks).order_by(tasks.c.created_at, tasks.c.id)
        ).mappings()
        return tuple(self._record(dict(row)) for row in rows)

    @staticmethod
    def _values(record: TaskRecord) -> RowData:
        task = record.task
        return {
            "id": str(task.id),
            "schema_version": record.schema_version,
            "status": task.status.value,
            "specification_json": task.specification.model_dump_json(),
            "current_sequence": task.sequence,
            "total_spend": str(task.total_spend),
            "cancel_requested": record.cancel_requested,
            "runtime_state_json": record.runtime_state.model_dump_json(),
            "created_at": _utc_text(task.created_at),
            "updated_at": _utc_text(task.updated_at),
        }

    @staticmethod
    def _record(row: RowData) -> TaskRecord:
        _supported_schema(row)
        try:
            specification = TaskSpecification.model_validate_json(row["specification_json"])
            task = Task(
                schema_version=1,
                id=UUID(cast("str", row["id"])),
                status=TaskStatus(cast("str", row["status"])),
                specification=specification,
                sequence=cast("int", row["current_sequence"]),
                total_spend=Decimal(cast("str", row["total_spend"])),
                created_at=_datetime(row["created_at"]),
                updated_at=_datetime(row["updated_at"]),
            )
            runtime_state = RuntimeSafeguardState.model_validate_json(row["runtime_state_json"])
            return TaskRecord(
                task=task,
                cancel_requested=bool(row["cancel_requested"]),
                runtime_state=runtime_state,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise _payload_error("task", error) from error


class SQLiteEventRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append(self, record: EventRecord) -> None:
        self.append_many((record,))

    def append_many(self, records: tuple[EventRecord, ...]) -> None:
        expected_by_task: dict[UUID, int] = {}
        pending_ids: set[UUID] = set()
        for record in records:
            if record.id in pending_ids or self._id_exists(record.id):
                raise DuplicateRecordError(f"event {record.id} already exists")
            task_id = record.event.task_id
            expected = expected_by_task.get(task_id)
            if expected is None:
                latest = self.latest(task_id)
                expected = 1 if latest is None else latest.event.sequence + 1
            if record.event.sequence != expected:
                raise SequenceConflictError(
                    f"expected event sequence {expected}, received {record.event.sequence}"
                )
            expected_by_task[task_id] = expected + 1
            pending_ids.add(record.id)
        if not records:
            return
        try:
            self._connection.execute(insert(events), [self._values(record) for record in records])
        except SQLAlchemyError as error:
            raise _write_error(error, "event") from error

    def list_for_task(self, task_id: UUID) -> tuple[EventRecord, ...]:
        rows = _read(
            self._connection,
            select(events).where(events.c.task_id == str(task_id)).order_by(events.c.sequence),
        ).mappings()
        return tuple(self._record(dict(row)) for row in rows)

    def latest(self, task_id: UUID) -> EventRecord | None:
        row = (
            _read(
                self._connection,
                select(events)
                .where(events.c.task_id == str(task_id))
                .order_by(events.c.sequence.desc())
                .limit(1),
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._record(dict(row))

    def get_by_sequence(self, task_id: UUID, sequence: int) -> EventRecord:
        row = (
            _read(
                self._connection,
                select(events).where(
                    events.c.task_id == str(task_id), events.c.sequence == sequence
                ),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecordNotFoundError(f"event {task_id}/{sequence} was not found")
        return self._record(dict(row))

    def _id_exists(self, event_id: UUID) -> bool:
        return (
            _read(
                self._connection, select(events.c.id).where(events.c.id == str(event_id))
            ).scalar_one_or_none()
            is not None
        )

    @staticmethod
    def _values(record: EventRecord) -> RowData:
        event = record.event
        return {
            "id": str(record.id),
            "schema_version": record.schema_version,
            "task_id": str(event.task_id),
            "sequence": event.sequence,
            "event_type": event.event_type.value,
            "timestamp": _utc_text(event.timestamp),
            "payload_json": _json(event.payload),
        }

    @staticmethod
    def _record(row: RowData) -> EventRecord:
        _supported_schema(row)
        try:
            payload = cast("dict[str, JsonValue]", json.loads(cast("str", row["payload_json"])))
            event = RuntimeEvent(
                task_id=UUID(cast("str", row["task_id"])),
                sequence=cast("int", row["sequence"]),
                event_type=RuntimeEventType(cast("str", row["event_type"])),
                timestamp=_datetime(row["timestamp"]),
                payload=payload,
            )
            return EventRecord(id=UUID(cast("str", row["id"])), event=event)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
            raise _payload_error("event", error) from error


class SQLiteApprovalRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, record: ApprovalRecord) -> None:
        try:
            self._connection.execute(insert(approvals).values(**self._values(record)))
        except SQLAlchemyError as error:
            raise _write_error(error, "approval") from error

    def get(self, approval_id: UUID) -> ApprovalRecord:
        row = (
            _read(self._connection, select(approvals).where(approvals.c.id == str(approval_id)))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecordNotFoundError(f"approval {approval_id} was not found")
        return self._record(dict(row))

    def get_pending_for_task(self, task_id: UUID) -> ApprovalRecord | None:
        row = (
            _read(
                self._connection,
                select(approvals)
                .where(
                    approvals.c.task_id == str(task_id),
                    approvals.c.status == ApprovalStatus.PENDING.value,
                )
                .order_by(approvals.c.created_at, approvals.c.id)
                .limit(1),
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._record(dict(row))

    def update(self, record: ApprovalRecord) -> None:
        current = self.get(record.approval.id)
        if current.approval.status is not ApprovalStatus.PENDING:
            raise StaleUpdateError(f"approval {record.approval.id} is already resolved")
        if (
            record.approval.task_id != current.approval.task_id
            or record.approval.action != current.approval.action
            or record.approval.created_at != current.approval.created_at
        ):
            raise StaleUpdateError(f"approval {record.approval.id} immutable data changed")
        try:
            self._connection.execute(
                update(approvals)
                .where(approvals.c.id == str(record.approval.id))
                .values(**self._values(record))
            )
        except SQLAlchemyError as error:
            raise _write_error(error, "approval") from error

    def list_for_task(self, task_id: UUID) -> tuple[ApprovalRecord, ...]:
        rows = _read(
            self._connection,
            select(approvals)
            .where(approvals.c.task_id == str(task_id))
            .order_by(approvals.c.created_at, approvals.c.id),
        ).mappings()
        return tuple(self._record(dict(row)) for row in rows)

    @staticmethod
    def _values(record: ApprovalRecord) -> RowData:
        approval = record.approval
        return {
            "id": str(approval.id),
            "schema_version": record.schema_version,
            "task_id": str(approval.task_id),
            "status": approval.status.value,
            "action_json": approval.action.model_dump_json(),
            "reason": record.reason,
            "created_at": _utc_text(approval.created_at),
            "resolved_at": (
                None if approval.resolved_at is None else _utc_text(approval.resolved_at)
            ),
        }

    @staticmethod
    def _record(row: RowData) -> ApprovalRecord:
        _supported_schema(row)
        try:
            resolved = row["resolved_at"]
            approval = ApprovalRequest(
                id=UUID(cast("str", row["id"])),
                task_id=UUID(cast("str", row["task_id"])),
                action=Action.model_validate_json(row["action_json"]),
                status=ApprovalStatus(cast("str", row["status"])),
                created_at=_datetime(row["created_at"]),
                resolved_at=None if resolved is None else _datetime(resolved),
            )
            reason = cast("str | None", row["reason"])
            return ApprovalRecord(approval=approval, reason=reason)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise _payload_error("approval", error) from error


class SQLiteSimulationRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, checkpoint: SimulationCheckpoint) -> None:
        if checkpoint.metadata.simulation_schema_version != 1:
            raise UnsupportedSchemaVersionError(
                "simulation checkpoint schema version is unsupported"
            )
        latest = self.latest(checkpoint.metadata.task_id)
        if (
            latest is not None
            and checkpoint.metadata.runtime_sequence <= latest.metadata.runtime_sequence
        ):
            raise StaleUpdateError(
                f"checkpoint sequence {checkpoint.metadata.runtime_sequence} is not newer than "
                f"{latest.metadata.runtime_sequence}"
            )
        try:
            self._connection.execute(
                insert(simulation_checkpoints).values(**self._values(checkpoint))
            )
        except SQLAlchemyError as error:
            raise _write_error(error, "simulation checkpoint") from error

    def latest(self, task_id: UUID) -> SimulationCheckpoint | None:
        row = (
            _read(
                self._connection,
                select(simulation_checkpoints)
                .where(simulation_checkpoints.c.task_id == str(task_id))
                .order_by(simulation_checkpoints.c.runtime_sequence.desc())
                .limit(1),
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._record(dict(row))

    def get_by_runtime_sequence(self, task_id: UUID, runtime_sequence: int) -> SimulationCheckpoint:
        row = (
            _read(
                self._connection,
                select(simulation_checkpoints).where(
                    simulation_checkpoints.c.task_id == str(task_id),
                    simulation_checkpoints.c.runtime_sequence == runtime_sequence,
                ),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecordNotFoundError(f"checkpoint {task_id}/{runtime_sequence} was not found")
        return self._record(dict(row))

    @staticmethod
    def _values(checkpoint: SimulationCheckpoint) -> RowData:
        metadata = checkpoint.metadata
        return {
            "id": str(metadata.id),
            "schema_version": checkpoint.schema_version,
            "task_id": str(metadata.task_id),
            "runtime_sequence": metadata.runtime_sequence,
            "simulation_tick": metadata.simulation_tick,
            "simulation_schema_version": metadata.simulation_schema_version,
            "adapter_type": metadata.adapter_type,
            "adapter_schema_version": metadata.adapter_schema_version,
            "adapter_observation_sequence": metadata.adapter_observation_sequence,
            "adapter_seed": metadata.adapter_seed,
            "state_json": _json(checkpoint.state),
            "created_at": _utc_text(metadata.created_at),
        }

    @staticmethod
    def _record(row: RowData) -> SimulationCheckpoint:
        _supported_schema(row)
        if row.get("simulation_schema_version") != 1:
            raise UnsupportedSchemaVersionError(
                "persisted simulation checkpoint schema version is unsupported"
            )
        try:
            metadata = CheckpointMetadata(
                id=UUID(cast("str", row["id"])),
                task_id=UUID(cast("str", row["task_id"])),
                runtime_sequence=cast("int", row["runtime_sequence"]),
                simulation_tick=cast("int", row["simulation_tick"]),
                simulation_schema_version=cast("int", row["simulation_schema_version"]),
                adapter_type=cast("str", row["adapter_type"]),
                adapter_schema_version=cast("int", row["adapter_schema_version"]),
                adapter_observation_sequence=cast("int", row["adapter_observation_sequence"]),
                adapter_seed=cast("str", row["adapter_seed"]),
                created_at=_datetime(row["created_at"]),
            )
            state = cast("dict[str, JsonValue]", json.loads(cast("str", row["state_json"])))
            return SimulationCheckpoint(metadata=metadata, state=state)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
            raise _payload_error("simulation checkpoint", error) from error
