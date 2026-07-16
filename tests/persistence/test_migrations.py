"""Alembic ownership, revision validation, and SQLite integrity tests."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from sim_pilot.persistence import (
    InvalidPersistedPayloadError,
    TransactionError,
    UnsupportedSchemaVersionError,
)
from sim_pilot.persistence.sqlite import (
    SQLiteUnitOfWork,
    create_sqlite_engine,
    upgrade_database,
    verify_database_revision,
)
from sim_pilot.persistence.sqlite.migrations import alembic_config
from tests.persistence.factories import TASK_ID, task_record


def database_url(tmp_path: Path, name: str = "migration.db") -> str:
    return f"sqlite:///{tmp_path / name}"


def test_empty_database_upgrades_to_head_and_repeated_upgrade_is_safe(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    verify_database_revision(engine)

    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "approvals",
        "events",
        "simulation_checkpoints",
        "tasks",
    }
    engine.dispose()


def test_initial_schema_has_expected_constraints_indexes_and_foreign_keys(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    inspector = inspect(engine)

    event_unique = inspector.get_unique_constraints("events")
    assert any(constraint["column_names"] == ["task_id", "sequence"] for constraint in event_unique)
    event_indexes = inspector.get_indexes("events")
    assert any(index["name"] == "ix_events_task_sequence" for index in event_indexes)
    checkpoint_indexes = inspector.get_indexes("simulation_checkpoints")
    assert any(index["name"] == "ix_checkpoints_task_latest" for index in checkpoint_indexes)
    approval_indexes = inspector.get_indexes("approvals")
    assert any(index["name"] == "uq_approvals_pending_action" for index in approval_indexes)
    assert inspector.get_foreign_keys("events")[0]["referred_table"] == "tasks"
    engine.dispose()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO events
                (id, schema_version, task_id, sequence, event_type, timestamp, payload_json)
                VALUES (:id, 1, :task_id, 1, 'task_created', :timestamp, '{}')"""
            ),
            {
                "id": "20000000-0000-0000-0000-000000000001",
                "task_id": str(TASK_ID),
                "timestamp": "2026-07-16T12:00:00Z",
            },
        )
    engine.dispose()


def test_missing_and_unknown_migration_state_fail_clearly(tmp_path: Path) -> None:
    missing_engine = create_sqlite_engine(database_url(tmp_path, "missing.db"))
    with pytest.raises(UnsupportedSchemaVersionError, match="no Alembic"):
        SQLiteUnitOfWork(missing_engine)
    missing_engine.dispose()

    unknown_engine = create_sqlite_engine(database_url(tmp_path, "unknown.db"))
    with unknown_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('9999')"))
    with pytest.raises(UnsupportedSchemaVersionError, match="9999"):
        verify_database_revision(unknown_engine)
    unknown_engine.dispose()


def test_repository_translates_unsupported_and_invalid_persisted_payloads(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    with SQLiteUnitOfWork(engine) as uow:
        uow.tasks.create(task_record())

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE tasks SET schema_version = 2 WHERE id = :id"), {"id": str(TASK_ID)}
        )
    with pytest.raises(UnsupportedSchemaVersionError), SQLiteUnitOfWork(engine) as uow:
        uow.tasks.get(TASK_ID)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE tasks SET schema_version = 1, specification_json = 'not-json' "
                "WHERE id = :id"
            ),
            {"id": str(TASK_ID)},
        )
    with pytest.raises(InvalidPersistedPayloadError), SQLiteUnitOfWork(engine) as uow:
        uow.tasks.get(TASK_ID)
    engine.dispose()


def test_initial_migration_downgrades_to_base(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    command.downgrade(alembic_config(url), "base")
    engine = create_sqlite_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert not {"tasks", "events", "approvals", "simulation_checkpoints"} & tables
    engine.dispose()


def test_sqlite_read_failures_are_translated_at_repository_boundary(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE tasks"))

    with pytest.raises(TransactionError, match="could not read"), SQLiteUnitOfWork(engine) as uow:
        uow.tasks.list()
    engine.dispose()
