"""Minimal process-facing CLI coverage."""

from pathlib import Path
from uuid import UUID

from typer.testing import CliRunner

from sim_pilot.cli import app


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
