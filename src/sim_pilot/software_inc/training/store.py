"""Owner-only SQLite persistence for Prompt 6B education workflows."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import UUID

from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import TrainingCycleEvent, TrainingWorkflow

DEFAULT_TRAINING_STORE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Sim Pilot"
    / "software-inc"
    / "training"
    / "workflows.sqlite3"
)


class TrainingWorkflowStore:
    def __init__(self, path: Path = DEFAULT_TRAINING_STORE) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS training_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    game_session_id TEXT NOT NULL,
                    save_identity TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_training_per_save
                ON training_workflows(game_session_id, save_identity)
                WHERE status NOT IN ('completed', 'blocked');
                CREATE TABLE IF NOT EXISTS training_events (
                    event_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    UNIQUE(workflow_id, sequence),
                    FOREIGN KEY(workflow_id) REFERENCES training_workflows(workflow_id)
                );
                """
            )
        self.path.chmod(0o600)

    def save(self, workflow: TrainingWorkflow) -> None:
        self.initialize()
        with self._connect() as connection:
            if workflow.status.value not in {"completed", "blocked"}:
                conflict = connection.execute(
                    "SELECT workflow_id FROM training_workflows WHERE game_session_id=? AND "
                    "save_identity=? AND status NOT IN ('completed','blocked') AND "
                    "workflow_id!=? LIMIT 1",
                    (workflow.game_session_id, workflow.save_identity, str(workflow.workflow_id)),
                ).fetchone()
                if conflict is not None:
                    raise SoftwareIncUIValidationError(
                        "another open education workflow already owns the current save"
                    )
            connection.execute(
                """INSERT INTO training_workflows(
                    workflow_id,game_session_id,save_identity,employee_id,status,body,updated_at
                ) VALUES(?,?,?,?,?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET
                    game_session_id=excluded.game_session_id, save_identity=excluded.save_identity,
                    employee_id=excluded.employee_id, status=excluded.status,
                    body=excluded.body, updated_at=excluded.updated_at""",
                (
                    str(workflow.workflow_id),
                    workflow.game_session_id,
                    workflow.save_identity,
                    workflow.employee_id,
                    workflow.status.value,
                    workflow.model_dump_json(),
                    workflow.updated_at.isoformat(),
                ),
            )

    def append_event(self, event: TrainingCycleEvent) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO training_events(event_id,workflow_id,sequence,body) VALUES(?,?,?,?)",
                (
                    str(event.event_id),
                    str(event.workflow_id),
                    event.sequence,
                    event.model_dump_json(),
                ),
            )

    def current(self, *, game_session_id: str, save_identity: str) -> TrainingWorkflow | None:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT body FROM training_workflows WHERE game_session_id=? AND save_identity=? "
                "AND status NOT IN ('completed','blocked') ORDER BY updated_at DESC LIMIT 2",
                (game_session_id, save_identity),
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError("multiple open education workflows exist for the current save")
        return None if not rows else TrainingWorkflow.model_validate_json(rows[0][0])

    def latest(self, *, game_session_id: str, save_identity: str) -> TrainingWorkflow | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT body FROM training_workflows WHERE game_session_id=? AND save_identity=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (game_session_id, save_identity),
            ).fetchone()
        return None if row is None else TrainingWorkflow.model_validate_json(row[0])

    def events(self, workflow_id: UUID) -> tuple[TrainingCycleEvent, ...]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT body FROM training_events WHERE workflow_id=? ORDER BY sequence",
                (str(workflow_id),),
            ).fetchall()
        return tuple(TrainingCycleEvent.model_validate_json(row[0]) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def store_is_owner_only(path: Path = DEFAULT_TRAINING_STORE) -> bool:
    return not path.exists() or (os.stat(path).st_mode & 0o077) == 0


__all__ = ["DEFAULT_TRAINING_STORE", "TrainingWorkflowStore", "store_is_owner_only"]
