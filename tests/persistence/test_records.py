"""Strict validation for storage-independent durable records."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sim_pilot.persistence import EventRecord, TaskRecord
from tests.persistence.factories import event_record, task_record


def test_durable_records_reject_unknown_fields_and_schema_versions() -> None:
    with pytest.raises(ValidationError):
        TaskRecord.model_validate({**task_record().model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        EventRecord.model_validate({**event_record(1).model_dump(), "schema_version": 2})


def test_task_record_rejects_non_utc_timestamps() -> None:
    eastern = timezone(-timedelta(hours=4))
    non_utc = task_record().task.model_copy(
        update={
            "created_at": datetime(2026, 7, 16, 8, tzinfo=eastern),
            "updated_at": datetime(2026, 7, 16, 8, tzinfo=eastern),
        }
    )
    with pytest.raises(ValidationError, match="timestamps must be UTC"):
        TaskRecord(task=non_utc)


def test_task_record_rejects_nested_schema_mismatch() -> None:
    future_task = task_record().task.model_copy(update={"schema_version": 2})
    with pytest.raises(ValidationError, match="schema version"):
        TaskRecord(task=future_task)
