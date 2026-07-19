"""Alembic ownership, revision validation, and SQLite integrity tests."""

import logging
import stat
from pathlib import Path
from typing import cast

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.engine import Transaction
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
from sim_pilot.persistence.sqlite.migrations import ALEMBIC_INI, alembic_config
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
    task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert "runtime_state_json" in task_columns
    checkpoint_columns = {
        column["name"] for column in inspect(engine).get_columns("simulation_checkpoints")
    }
    assert {
        "adapter_type",
        "adapter_schema_version",
        "adapter_observation_sequence",
        "adapter_seed",
    } <= checkpoint_columns
    engine.dispose()


def test_database_and_sidecar_permissions_are_owner_only(tmp_path: Path) -> None:
    url = database_url(tmp_path, "private.db")
    database = tmp_path / "private.db"
    sidecar = tmp_path / "private.db-wal"
    database.touch(mode=0o666)
    sidecar.touch(mode=0o666)
    database.chmod(0o666)
    sidecar.chmod(0o666)

    upgrade_database(url)
    engine = create_sqlite_engine(url)
    with engine.begin() as connection:
        connection.execute(text("SELECT 1"))

    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    engine.dispose()


def test_raw_alembic_upgrade_secures_database_permissions(tmp_path: Path) -> None:
    url = database_url(tmp_path, "alembic-private.db")
    database = tmp_path / "alembic-private.db"

    command.upgrade(alembic_config(url), "head")

    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_raw_alembic_uses_application_database_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "configured-raw-alembic.db"
    monkeypatch.setenv("SIM_PILOT_DATABASE", str(database))

    command.upgrade(Config(str(ALEMBIC_INI)), "head")

    assert database.exists()
    engine = create_sqlite_engine(f"sqlite:///{database}")
    verify_database_revision(engine)
    engine.dispose()


def test_programmatic_alembic_url_wins_over_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit.db"
    ambient = tmp_path / "ambient.db"
    monkeypatch.setenv("SIM_PILOT_DATABASE", str(ambient))

    command.upgrade(alembic_config(f"sqlite:///{explicit}"), "head")

    assert explicit.exists()
    assert not ambient.exists()


def test_programmatic_migration_does_not_disable_application_loggers(tmp_path: Path) -> None:
    application_logger = logging.getLogger("sim_pilot.test.migration-observability")
    application_logger.disabled = False

    command.upgrade(alembic_config(database_url(tmp_path, "logging.db")), "head")

    assert application_logger.disabled is False


def test_task_4a_database_upgrades_to_task_4b_with_runtime_defaults(tmp_path: Path) -> None:
    url = database_url(tmp_path, "upgrade-4a.db")
    command.upgrade(alembic_config(url), "0001")
    engine = create_sqlite_engine(url)
    record = task_record()
    task = record.task
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO tasks
                (id, schema_version, status, specification_json, current_sequence,
                 total_spend, cancel_requested, created_at, updated_at)
                VALUES (:id, 1, :status, :specification, 0, '0', 0, :created_at, :updated_at)"""
            ),
            {
                "id": str(task.id),
                "status": task.status.value,
                "specification": task.specification.model_dump_json(),
                "created_at": task.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": task.updated_at.isoformat().replace("+00:00", "Z"),
            },
        )
    engine.dispose()

    upgrade_database(url)
    upgraded_engine = create_sqlite_engine(url)
    uow = SQLiteUnitOfWork(upgraded_engine)
    uow.begin()
    try:
        upgraded = uow.tasks.get(task.id)
    finally:
        uow.rollback()
    assert upgraded.runtime_state.iterations == 0
    assert upgraded.runtime_state.approved_once_action is None
    upgraded_engine.dispose()


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


def test_commit_cleanup_failures_do_not_replace_primary_transaction_error() -> None:
    class FailingTransaction:
        is_active = True

        def commit(self) -> None:
            raise SQLAlchemyError("commit failed")

        def rollback(self) -> None:
            raise SQLAlchemyError("rollback failed")

    class FailingConnection:
        def begin(self) -> Transaction:
            return cast("Transaction", FailingTransaction())

        def close(self) -> None:
            raise SQLAlchemyError("close failed")

    class FailingEngine:
        def connect(self) -> Connection:
            return cast("Connection", FailingConnection())

    uow = SQLiteUnitOfWork(cast("Engine", FailingEngine()), verify_revision=False)
    uow.begin()

    with pytest.raises(TransactionError, match="could not commit transaction") as caught:
        uow.commit()

    assert any("rollback after commit failure" in note for note in caught.value.__notes__)
    assert any("transaction connection close" in note for note in caught.value.__notes__)
