"""Reusable behavior contract for in-memory and SQLite repositories."""

from datetime import timedelta
from uuid import UUID

import pytest

from sim_pilot.domain import TaskStatus
from sim_pilot.persistence import (
    DuplicateRecordError,
    RecordNotFoundError,
    SequenceConflictError,
    StaleUpdateError,
    UnsupportedSchemaVersionError,
)
from sim_pilot.runtime.models import ApprovalStatus
from tests.persistence.conftest import UnitOfWorkFactory
from tests.persistence.factories import (
    NOW,
    TASK_ID,
    approval_record,
    checkpoint,
    event_record,
    task_record,
)


def create_task(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.tasks.create(task_record())


def test_task_create_get_update_list_and_duplicate_rejection(
    uow_factory: UnitOfWorkFactory,
) -> None:
    original = task_record()
    updated = task_record(
        status=TaskStatus.RUNNING,
        sequence=3,
        updated_at=NOW + timedelta(minutes=1),
        cancel_requested=True,
    )
    with uow_factory() as uow:
        uow.tasks.create(original)

    with uow_factory() as uow:
        assert uow.tasks.get(TASK_ID) == original
        assert uow.tasks.list() == (original,)
        uow.tasks.update(updated)

    with uow_factory() as uow:
        stored = uow.tasks.get(TASK_ID)
        assert stored == updated
        assert stored.task.status is TaskStatus.RUNNING
        assert stored.task.total_spend.as_tuple() == updated.task.total_spend.as_tuple()
        assert stored.task.created_at.utcoffset() == timedelta(0)
        assert stored.cancel_requested

    with pytest.raises(DuplicateRecordError), uow_factory() as uow:
        uow.tasks.create(original)


def test_task_missing_and_stale_update(uow_factory: UnitOfWorkFactory) -> None:
    missing_id = UUID("10000000-0000-0000-0000-000000000099")
    with pytest.raises(RecordNotFoundError), uow_factory() as uow:
        uow.tasks.get(missing_id)

    create_task(uow_factory)
    current = task_record(sequence=2, updated_at=NOW + timedelta(minutes=2))
    with uow_factory() as uow:
        uow.tasks.update(current)

    with pytest.raises(StaleUpdateError), uow_factory() as uow:
        uow.tasks.update(task_record(sequence=1, updated_at=NOW + timedelta(minutes=1)))


def test_event_append_order_lookup_and_conflicts(uow_factory: UnitOfWorkFactory) -> None:
    create_task(uow_factory)
    first, second = event_record(1), event_record(2)
    with uow_factory() as uow:
        uow.events.append(first)
        uow.events.append(second)

    with uow_factory() as uow:
        assert uow.events.list_for_task(TASK_ID) == (first, second)
        assert uow.events.latest(TASK_ID) == second
        assert uow.events.get_by_sequence(TASK_ID, 1) == first

    duplicate_sequence = event_record(2).model_copy(
        update={"id": UUID("20000000-0000-0000-0000-000000000099")}
    )
    with pytest.raises(SequenceConflictError), uow_factory() as uow:
        uow.events.append(duplicate_sequence)
    with pytest.raises(SequenceConflictError), uow_factory() as uow:
        uow.events.append(event_record(4))
    with pytest.raises(RecordNotFoundError), uow_factory() as uow:
        uow.events.get_by_sequence(TASK_ID, 99)


def test_event_append_many_is_atomic(uow_factory: UnitOfWorkFactory) -> None:
    create_task(uow_factory)
    with uow_factory() as uow:
        uow.events.append(event_record(1))

    with pytest.raises(SequenceConflictError), uow_factory() as uow:
        uow.events.append_many((event_record(2), event_record(4)))

    with uow_factory() as uow:
        assert uow.events.list_for_task(TASK_ID) == (event_record(1),)


def test_event_duplicate_stable_identifier_is_rejected(uow_factory: UnitOfWorkFactory) -> None:
    create_task(uow_factory)
    first = event_record(1)
    with uow_factory() as uow:
        uow.events.append(first)
    duplicate_id = event_record(2).model_copy(update={"id": first.id})
    with pytest.raises(DuplicateRecordError), uow_factory() as uow:
        uow.events.append(duplicate_id)


@pytest.mark.parametrize("resolved_status", (ApprovalStatus.APPROVED, ApprovalStatus.DENIED))
def test_approval_pending_resolution_and_history(
    uow_factory: UnitOfWorkFactory, resolved_status: ApprovalStatus
) -> None:
    create_task(uow_factory)
    pending = approval_record()
    with uow_factory() as uow:
        uow.approvals.create(pending)
        assert uow.approvals.get_pending_for_task(TASK_ID) == pending

    resolved = approval_record(status=resolved_status)
    with uow_factory() as uow:
        uow.approvals.update(resolved)

    with uow_factory() as uow:
        stored = uow.approvals.get(pending.approval.id)
        assert stored.approval.status is resolved_status
        assert stored.approval.resolved_at is not None
        assert stored.reason == f"approval {resolved_status.value}"
        assert uow.approvals.get_pending_for_task(TASK_ID) is None
        assert uow.approvals.list_for_task(TASK_ID) == (resolved,)


def test_duplicate_pending_approval_for_same_action_is_rejected(
    uow_factory: UnitOfWorkFactory,
) -> None:
    create_task(uow_factory)
    with uow_factory() as uow:
        uow.approvals.create(approval_record(identifier=1))
    with pytest.raises(DuplicateRecordError), uow_factory() as uow:
        uow.approvals.create(approval_record(identifier=2))


def test_approval_history_is_deterministically_ordered(uow_factory: UnitOfWorkFactory) -> None:
    create_task(uow_factory)
    first = approval_record(identifier=1)
    resolved_first = approval_record(identifier=1, status=ApprovalStatus.APPROVED)
    second = approval_record(identifier=2, action_type="repair")
    with uow_factory() as uow:
        uow.approvals.create(first)
        uow.approvals.update(resolved_first)
        uow.approvals.create(second)

    with uow_factory() as uow:
        assert uow.approvals.list_for_task(TASK_ID) == (resolved_first, second)
        assert uow.approvals.get_pending_for_task(TASK_ID) == second
    with pytest.raises(RecordNotFoundError), uow_factory() as uow:
        uow.approvals.get(UUID("30000000-0000-0000-0000-000000000099"))


def test_checkpoint_round_trip_latest_and_stale_rejection(
    uow_factory: UnitOfWorkFactory,
) -> None:
    create_task(uow_factory)
    first, latest = checkpoint(1), checkpoint(3)
    with uow_factory() as uow:
        uow.simulations.save(first)
        uow.simulations.save(latest)

    with uow_factory() as uow:
        assert uow.simulations.latest(TASK_ID) == latest
        assert uow.simulations.get_by_runtime_sequence(TASK_ID, 1) == first
        assert uow.simulations.latest(TASK_ID).state == latest.state  # type: ignore[union-attr]

    with pytest.raises(StaleUpdateError), uow_factory() as uow:
        uow.simulations.save(checkpoint(2))
    with pytest.raises(RecordNotFoundError), uow_factory() as uow:
        uow.simulations.get_by_runtime_sequence(TASK_ID, 99)


def test_checkpoint_rejects_unsupported_simulation_schema(
    uow_factory: UnitOfWorkFactory,
) -> None:
    create_task(uow_factory)
    with pytest.raises(UnsupportedSchemaVersionError), uow_factory() as uow:
        uow.simulations.save(checkpoint(1, simulation_schema_version=2))


def test_unit_of_work_commit_explicit_and_automatic_rollback(
    uow_factory: UnitOfWorkFactory,
) -> None:
    uow = uow_factory()
    uow.begin()
    uow.tasks.create(task_record())
    uow.rollback()
    with uow_factory() as reader, pytest.raises(RecordNotFoundError):
        reader.tasks.get(TASK_ID)

    with pytest.raises(RuntimeError, match="abort"), uow_factory() as failing:
        failing.tasks.create(task_record())
        raise RuntimeError("abort")
    with uow_factory() as reader, pytest.raises(RecordNotFoundError):
        reader.tasks.get(TASK_ID)

    uow = uow_factory()
    uow.begin()
    uow.tasks.create(task_record())
    uow.commit()
    with uow_factory() as reader:
        assert reader.tasks.get(TASK_ID) == task_record()


def test_unit_of_work_is_atomic_across_repositories(
    uow_factory: UnitOfWorkFactory,
) -> None:
    with pytest.raises(RuntimeError, match="crash"), uow_factory() as uow:
        uow.tasks.create(task_record())
        uow.events.append(event_record(1))
        uow.approvals.create(approval_record())
        uow.simulations.save(checkpoint(1))
        raise RuntimeError("crash")

    with uow_factory() as reader:
        with pytest.raises(RecordNotFoundError):
            reader.tasks.get(TASK_ID)
        assert reader.events.list_for_task(TASK_ID) == ()
        assert reader.approvals.list_for_task(TASK_ID) == ()
        assert reader.simulations.latest(TASK_ID) is None


def test_unit_of_work_commits_all_repositories_together(
    uow_factory: UnitOfWorkFactory,
) -> None:
    task = task_record()
    event = event_record(1)
    approval = approval_record()
    simulation = checkpoint(1)
    with uow_factory() as uow:
        uow.tasks.create(task)
        uow.events.append(event)
        uow.approvals.create(approval)
        uow.simulations.save(simulation)

    with uow_factory() as reader:
        assert reader.tasks.get(TASK_ID) == task
        assert reader.events.list_for_task(TASK_ID) == (event,)
        assert reader.approvals.list_for_task(TASK_ID) == (approval,)
        assert reader.simulations.latest(TASK_ID) == simulation
