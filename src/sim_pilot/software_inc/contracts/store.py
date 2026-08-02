"""Owner-only SQLite persistence for the contract-specific Prompt 6A workflow."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import UUID

from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import ContractCycleEvent, ContractWorkflow

DEFAULT_CONTRACT_STORE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Sim Pilot"
    / "software-inc"
    / "contracts"
    / "workflows.sqlite3"
)


class ContractWorkflowStore:
    def __init__(self, path: Path = DEFAULT_CONTRACT_STORE) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contract_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    game_session_id TEXT NOT NULL,
                    save_identity TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                DROP INDEX IF EXISTS one_open_contract_identity;
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_contract_per_save
                ON contract_workflows(game_session_id, save_identity)
                WHERE status NOT IN ('completed', 'failed');
                CREATE TABLE IF NOT EXISTS contract_events (
                    event_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    UNIQUE(workflow_id, sequence),
                    FOREIGN KEY(workflow_id) REFERENCES contract_workflows(workflow_id)
                );
                """
            )
        self.path.chmod(0o600)

    def save(self, workflow: ContractWorkflow) -> None:
        self.initialize()
        with self._connect() as connection:
            if workflow.status.value not in {"completed", "failed"}:
                conflict = connection.execute(
                    """
                    SELECT workflow_id FROM contract_workflows
                    WHERE game_session_id = ? AND save_identity = ?
                      AND status NOT IN ('completed', 'failed')
                      AND workflow_id != ?
                    LIMIT 1
                    """,
                    (
                        workflow.game_session_id,
                        workflow.save_identity,
                        str(workflow.workflow_id),
                    ),
                ).fetchone()
                if conflict is not None:
                    raise SoftwareIncUIValidationError(
                        "another open contract workflow already owns the current save"
                    )
            connection.execute(
                """
                INSERT INTO contract_workflows(
                    workflow_id, game_session_id, save_identity, contract_id,
                    status, body, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    game_session_id=excluded.game_session_id,
                    save_identity=excluded.save_identity,
                    contract_id=excluded.contract_id,
                    status=excluded.status,
                    body=excluded.body,
                    updated_at=excluded.updated_at
                """,
                (
                    str(workflow.workflow_id),
                    workflow.game_session_id,
                    workflow.save_identity,
                    workflow.contract_id,
                    workflow.status.value,
                    workflow.model_dump_json(),
                    workflow.updated_at.isoformat(),
                ),
            )

    def append_event(self, event: ContractCycleEvent) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO contract_events(event_id, workflow_id, sequence, body) "
                "VALUES (?, ?, ?, ?)",
                (
                    str(event.event_id),
                    str(event.workflow_id),
                    event.sequence,
                    event.model_dump_json(),
                ),
            )

    def get(self, workflow_id: UUID) -> ContractWorkflow | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT body FROM contract_workflows WHERE workflow_id = ?", (str(workflow_id),)
            ).fetchone()
        return None if row is None else ContractWorkflow.model_validate_json(row[0])

    def current(self, *, game_session_id: str, save_identity: str) -> ContractWorkflow | None:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT body FROM contract_workflows
                WHERE game_session_id = ? AND save_identity = ?
                  AND status NOT IN ('completed', 'failed')
                ORDER BY updated_at DESC LIMIT 2
                """,
                (game_session_id, save_identity),
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError("multiple open contract workflows exist for the current save")
        return None if not rows else ContractWorkflow.model_validate_json(rows[0][0])

    def events(self, workflow_id: UUID) -> tuple[ContractCycleEvent, ...]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT body FROM contract_events WHERE workflow_id = ? ORDER BY sequence",
                (str(workflow_id),),
            ).fetchall()
        return tuple(ContractCycleEvent.model_validate_json(row[0]) for row in rows)

    def latest(self, *, game_session_id: str, save_identity: str) -> ContractWorkflow | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT body FROM contract_workflows
                WHERE game_session_id = ? AND save_identity = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (game_session_id, save_identity),
            ).fetchone()
        return None if row is None else ContractWorkflow.model_validate_json(row[0])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def store_is_owner_only(path: Path = DEFAULT_CONTRACT_STORE) -> bool:
    return not path.exists() or (os.stat(path).st_mode & 0o077) == 0


__all__ = ["ContractWorkflowStore", "DEFAULT_CONTRACT_STORE", "store_is_owner_only"]
