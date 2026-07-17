"""Minimal process-facing CLI coverage."""

from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from sim_pilot.cli import app
from sim_pilot.intent_compiler import IntentCompiler
from sim_pilot.intent_compiler.providers import ScriptedCompilerProvider
from tests.intent_compiler.helpers import response, valid_specification


def test_database_create_run_show_events_and_cancel(tmp_path: Path) -> None:
    runner = CliRunner()
    database = str(tmp_path / "cli.db")
    task_id = UUID(int=901)
    prefix = ["--database", database]

    upgraded = runner.invoke(app, [*prefix, "db", "upgrade"])
    assert upgraded.exit_code == 0, upgraded.output
    created = runner.invoke(
        app,
        [*prefix, "task", "create", "--task-id", str(task_id), "--target-cash", "1000000"],
    )
    assert created.exit_code == 0, created.output
    sliced = runner.invoke(app, [*prefix, "task", "run", str(task_id), "--iterations", "1"])
    assert sliced.exit_code == 0, sliced.output
    shown = runner.invoke(app, [*prefix, "task", "show", str(task_id)])
    assert shown.exit_code == 0
    assert '"status": "running"' in shown.output
    events = runner.invoke(app, [*prefix, "task", "events", str(task_id)])
    assert events.exit_code == 0
    assert "action_prepared" in events.output
    cancelled = runner.invoke(app, [*prefix, "task", "cancel", str(task_id)])
    assert cancelled.exit_code == 0


def test_compile_and_create_from_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    database = str(tmp_path / "compiler-cli.db")
    prefix = ["--database", database]
    task_id = UUID(int=902)
    responses = [response(valid_specification()), response(valid_specification())]
    compiler = IntentCompiler(ScriptedCompilerProvider(responses))
    monkeypatch.setattr("sim_pilot.cli._intent_compiler", lambda: compiler)

    assert runner.invoke(app, [*prefix, "db", "upgrade"]).exit_code == 0
    compiled = runner.invoke(
        app, [*prefix, "task", "compile", "--instruction", "Reach one million cash."]
    )
    assert compiled.exit_code == 0, compiled.output
    assert '"validation_status": "valid"' in compiled.output

    created = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "create",
            "--instruction",
            "Reach one million cash.",
            "--task-id",
            str(task_id),
            "--yes",
        ],
    )
    assert created.exit_code == 0, created.output
    shown = runner.invoke(app, [*prefix, "task", "show", str(task_id)])
    assert shown.exit_code == 0
    assert "Reach one million cash." in shown.output


def test_instruction_creation_requires_valid_compilation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    database = str(tmp_path / "invalid-compiler-cli.db")
    compiler = IntentCompiler(
        ScriptedCompilerProvider(
            [response(ambiguities=("Minimum reserve amount was not specified.",))]
        )
    )
    monkeypatch.setattr("sim_pilot.cli._intent_compiler", lambda: compiler)
    assert runner.invoke(app, ["--database", database, "db", "upgrade"]).exit_code == 0
    result = runner.invoke(
        app,
        [
            "--database",
            database,
            "task",
            "create",
            "--instruction",
            "Keep enough cash available.",
            "--yes",
        ],
    )
    assert result.exit_code == 20
    assert "clarification_required" in result.output
