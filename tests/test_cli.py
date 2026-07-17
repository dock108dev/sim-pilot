"""Minimal process-facing CLI coverage."""

from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from sim_pilot.cli import CompilerProviderName, ReferenceDemoDecisionProvider, app
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
    sliced = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "run",
            str(task_id),
            "--iterations",
            "1",
            "--decision-provider",
            "scripted",
        ],
    )
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

    def compiler_factory(
        provider_name: CompilerProviderName, recording_directory: Path | None
    ) -> IntentCompiler:
        del provider_name, recording_directory
        return compiler

    monkeypatch.setattr("sim_pilot.cli._intent_compiler", compiler_factory)

    assert runner.invoke(app, [*prefix, "db", "upgrade"]).exit_code == 0
    compiled = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "compile",
            "--instruction",
            "Reach one million cash.",
            "--provider",
            "openai",
        ],
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
            "--provider",
            "openai",
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

    def compiler_factory(
        provider_name: CompilerProviderName, recording_directory: Path | None
    ) -> IntentCompiler:
        del provider_name, recording_directory
        return compiler

    monkeypatch.setattr("sim_pilot.cli._intent_compiler", compiler_factory)
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
            "--provider",
            "openai",
            "--yes",
        ],
    )
    assert result.exit_code == 20
    assert "clarification_required" in result.output


def test_compiler_provider_must_be_selected_explicitly() -> None:
    result = CliRunner().invoke(
        app,
        ["task", "compile", "--instruction", "Reach one million cash."],
    )
    assert result.exit_code == 20
    assert "no compiler provider configured" in result.output
    assert "--provider openai" in result.output


def test_runtime_decision_provider_defaults_to_none_without_hosted_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_hosted_provider(**kwargs: object) -> None:
        del kwargs
        raise AssertionError("hosted provider must not be constructed by default")

    monkeypatch.setattr("sim_pilot.cli.OpenAIDecisionProvider", unexpected_hosted_provider)
    result = CliRunner().invoke(
        app,
        ["task", "run", str(UUID(int=999))],
    )
    assert result.exit_code == 20
    assert "no decision provider configured" in result.output


def test_scripted_runtime_recording_is_opt_in_and_atomic(tmp_path: Path) -> None:
    runner = CliRunner()
    database = str(tmp_path / "recording-cli.db")
    recordings = tmp_path / "decision-recordings"
    task_id = UUID(int=903)
    prefix = ["--database", database]
    assert runner.invoke(app, [*prefix, "db", "upgrade"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [*prefix, "task", "create", "--task-id", str(task_id), "--target-cash", "510000"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "run",
            str(task_id),
            "--decision-provider",
            "scripted",
            "--record-dir",
            str(recordings),
            "--iterations",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    paths = tuple(recordings.iterdir())
    assert len(paths) == 1
    assert paths[0].suffix == ".json"
    assert paths[0].stat().st_mode & 0o077 == 0
    assert '"provider": "scripted"' in paths[0].read_text()


def test_openai_runtime_provider_requires_explicit_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed: list[dict[str, object]] = []

    def fake_openai_provider(**kwargs: object) -> ReferenceDemoDecisionProvider:
        constructed.append(kwargs)
        return ReferenceDemoDecisionProvider()

    monkeypatch.setattr("sim_pilot.cli.OpenAIDecisionProvider", fake_openai_provider)
    runner = CliRunner()
    database = str(tmp_path / "openai-selection.db")
    task_id = UUID(int=904)
    prefix = ["--database", database]
    assert runner.invoke(app, [*prefix, "db", "upgrade"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [*prefix, "task", "create", "--task-id", str(task_id), "--target-cash", "510000"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "run",
            str(task_id),
            "--decision-provider",
            "openai",
            "--iterations",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(constructed) == 1
    assert constructed[0]["model"]
    assert constructed[0]["timeout_seconds"] == 30
