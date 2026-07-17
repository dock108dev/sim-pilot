"""Minimal process-facing CLI coverage."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from sim_pilot.cli import CompilerProviderName, ReferenceDemoDecisionProvider, app
from sim_pilot.domain import Observation
from sim_pilot.intent_compiler import IntentCompiler
from sim_pilot.intent_compiler.providers import ScriptedCompilerProvider
from sim_pilot.openttd.config import OpenTTDConfiguration
from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from sim_pilot.openttd.models import OpenTTDAdapterCapabilities, OpenTTDObservationState
from tests.intent_compiler.helpers import response, valid_specification
from tests.openttd.gamescript.helpers import capabilities, snapshot
from tests.openttd.helpers import FakeOpenTTDClient, state


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
        provider_name: CompilerProviderName,
        recording_directory: Path | None,
        adapter_name: object,
    ) -> IntentCompiler:
        del provider_name, recording_directory, adapter_name
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
        provider_name: CompilerProviderName,
        recording_directory: Path | None,
        adapter_name: object,
    ) -> IntentCompiler:
        del provider_name, recording_directory, adapter_name
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


def test_openttd_capabilities_is_offline_and_provider_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("OpenTTD capabilities must not initialize external clients")

    monkeypatch.setattr("sim_pilot.cli._intent_compiler", unexpected)
    monkeypatch.setattr("sim_pilot.cli._decision_provider", unexpected)
    monkeypatch.setattr("sim_pilot.cli.openttd_configuration", unexpected)

    result = CliRunner().invoke(app, ["openttd", "capabilities"])

    assert result.exit_code == 0, result.output
    assert '"read_state": true' in result.output
    assert '"execute_actions": false' in result.output


def test_openttd_doctor_reports_missing_local_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIM_PILOT_OPENTTD_ADMIN_PASSWORD", raising=False)

    result = CliRunner().invoke(app, ["openttd", "doctor"])

    assert result.exit_code == 0, result.output
    assert '"configuration_valid": false' in result.output
    assert "SIM_PILOT_OPENTTD_ADMIN_PASSWORD is required" in result.output


def test_openttd_observe_uses_local_observation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def capture() -> Observation:
        return Observation(
            sequence=1,
            timestamp=datetime.now(UTC),
            tick=712223,
            summary="Local fixture observation.",
            state={"source": "openttd"},
        )

    monkeypatch.setattr("sim_pilot.cli._capture_openttd_observation", capture)

    result = CliRunner().invoke(app, ["openttd", "observe"])

    assert result.exit_code == 0, result.output
    assert "Local fixture observation." in result.output


def test_openttd_bridge_doctor_reports_negotiated_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health = BridgeHealth(
        connected=True,
        authenticated=True,
        openttd_version="15.3",
        bridge_detected=True,
        bridge_protocol_version=1,
        script_version=1,
        script_instance_id="cli-bridge",
        last_sequence=4,
        last_snapshot_at=datetime.now(UTC),
        synchronization_state=SynchronizationState.SYNCHRONIZED,
        active_company_context=0,
        capability_fingerprint=capabilities().fingerprint,
        capabilities=capabilities(),
        snapshot=snapshot(),
    )
    combined = OpenTTDObservationState.from_combined_state(
        state(),
        health,
        OpenTTDAdapterCapabilities(
            bridge_detected=True,
            supports_full_snapshots=True,
            bridge_read_resources=capabilities().readable_resources,
            bridge_actions=capabilities().supported_actions,
        ),
    )
    observation = Observation(
        sequence=1,
        timestamp=datetime.now(UTC),
        tick=712223,
        summary="Combined fixture.",
        state=combined.model_dump(mode="json"),
    )

    async def capture() -> tuple[Observation, BridgeHealth]:
        return observation, health

    monkeypatch.setattr("sim_pilot.cli._bridge_observation", capture)
    result = CliRunner().invoke(app, ["openttd", "bridge", "doctor"])

    assert result.exit_code == 0, result.output
    assert '"script_instance_id": "cli-bridge"' in result.output
    assert '"synchronization_state": "synchronized"' in result.output


def test_openttd_watch_is_bounded_and_emits_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = OpenTTDConfiguration(password=SecretStr("local"), polling_interval_seconds=0.1)
    fake = FakeOpenTTDClient([state("initial_company"), state("profitable_company")])

    def client_factory(configuration: OpenTTDConfiguration) -> FakeOpenTTDClient:
        del configuration
        return fake

    monkeypatch.setattr("sim_pilot.cli.openttd_configuration", lambda: configuration)
    monkeypatch.setattr("sim_pilot.cli.OpenTTDAdminClient", client_factory)

    result = CliRunner().invoke(app, ["openttd", "watch", "--count", "2"])

    assert result.exit_code == 0, result.output
    assert result.output.count('"sequence"') == 2
    assert '"cash": 425000' in result.output
    assert fake.closed is True
