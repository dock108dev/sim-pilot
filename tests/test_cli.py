"""Minimal process-facing CLI coverage."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from sim_pilot.cli import INVALID_INPUT, CompilerProviderName, ReferenceDemoDecisionProvider, app
from sim_pilot.domain import (
    CapabilityCoverage,
    Company,
    Observation,
    WorldSnapshot,
    WorldSnapshotMetadata,
)
from sim_pilot.domain.world import CoverageStatus
from sim_pilot.intent_compiler import IntentCompiler
from sim_pilot.intent_compiler.providers import ScriptedCompilerProvider
from sim_pilot.openttd.config import OpenTTDConfiguration
from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from sim_pilot.openttd.models import OpenTTDAdapterCapabilities, OpenTTDObservationState
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLICompatibilityError,
    CodexCLIExecutableNotFoundError,
    CodexCLIUnauthenticatedError,
)
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
from sim_pilot.runtime.decision_errors import DecisionProviderUnavailableError
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
        model_name: str | None,
    ) -> IntentCompiler:
        del provider_name, recording_directory, adapter_name, model_name
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
        model_name: str | None,
    ) -> IntentCompiler:
        del provider_name, recording_directory, adapter_name, model_name
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
    assert "--provider openai or --provider codex" in result.output


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
    assert "error[DecisionProviderNotConfiguredError]" in result.output


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


def test_codex_compiler_is_explicit_and_uses_selected_model_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    constructed: list[dict[str, object]] = []

    def fake_codex_provider(**kwargs: object) -> ScriptedCompilerProvider:
        constructed.append(kwargs)
        return ScriptedCompilerProvider([response(valid_specification())])

    monkeypatch.setattr("sim_pilot.cli.CodexCLICompilerProvider", fake_codex_provider)
    result = CliRunner().invoke(
        app,
        [
            "task",
            "compile",
            "--provider",
            "codex",
            "--model",
            "gpt-test",
            "--instruction",
            "Reach one million cash.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert constructed[0]["model"] == "gpt-test"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (CodexCLIExecutableNotFoundError("missing executable"), "missing executable"),
        (CodexCLIUnauthenticatedError("run codex login"), "run codex login"),
        (CodexCLICompatibilityError("upgrade Codex CLI"), "upgrade Codex CLI"),
    ],
)
def test_codex_compiler_capability_failures_have_deterministic_cli_exit(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def fail_provider(**kwargs: object) -> None:
        del kwargs
        raise error

    monkeypatch.setattr("sim_pilot.cli.CodexCLICompilerProvider", fail_provider)
    result = CliRunner().invoke(
        app,
        [
            "task",
            "compile",
            "--provider",
            "codex",
            "--instruction",
            "Reach one million cash.",
        ],
    )

    assert result.exit_code == 20
    assert message in result.output


def test_codex_decision_is_explicit_and_uses_selected_model_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SIM_PILOT_CODEX_MODEL", "gpt-codex-test")
    monkeypatch.setenv("SIM_PILOT_DECISION_MODEL", "gpt-api-test")
    constructed: list[dict[str, object]] = []

    def fake_codex_provider(**kwargs: object) -> ReferenceDemoDecisionProvider:
        constructed.append(kwargs)
        return ReferenceDemoDecisionProvider()

    monkeypatch.setattr("sim_pilot.cli.CodexCLIDecisionProvider", fake_codex_provider)
    runner = CliRunner()
    database = str(tmp_path / "codex-selection.db")
    task_id = UUID(int=905)
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
            "codex",
            "--iterations",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert constructed[0]["model"] == "gpt-codex-test"


def test_failed_current_run_does_not_print_stale_decision_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingProvider:
        async def decide(self, context: DecisionContext) -> DecisionProviderResult:
            del context
            raise DecisionProviderUnavailableError("current provider failed")

    def failing_provider(**kwargs: object) -> FailingProvider:
        del kwargs
        return FailingProvider()

    monkeypatch.setattr("sim_pilot.cli.CodexCLIDecisionProvider", failing_provider)
    runner = CliRunner()
    task_id = UUID(int=906)
    prefix = ["--database", str(tmp_path / "metadata-correlation.db")]
    assert runner.invoke(app, [*prefix, "db", "upgrade"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [*prefix, "task", "create", "--task-id", str(task_id), "--target-cash", "1000000"],
        ).exit_code
        == 0
    )
    first = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "run",
            str(task_id),
            "--decision-provider",
            "scripted",
            "--iterations",
            "1",
        ],
    )
    assert "decision_metadata" in first.output

    failed = runner.invoke(
        app,
        [
            *prefix,
            "task",
            "resume",
            str(task_id),
            "--decision-provider",
            "codex",
            "--iterations",
            "1",
        ],
    )
    assert failed.exit_code != 0
    assert "current provider failed" in failed.output
    assert "decision_metadata" not in failed.output


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


def test_openttd_world_commands_render_tables_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id="world-1",
            world_id="fixture-world",
            game="openttd",
            game_version="15.3",
            game_date=712223,
            capture_started_game_date=712223,
            capture_completed_game_date=712223,
            complete=True,
            capability_fingerprint="fingerprint",
            save_generation=2,
            bridge_sequence=4,
            captured_at=datetime.now(UTC),
        ),
        coverage=(CapabilityCoverage(category="companies", status=CoverageStatus.AVAILABLE),),
        companies=(
            Company(
                id="company:opaque-identifier",
                name="Fixture Transport",
                cash=425000,
                loan=50000,
            ),
        ),
    )

    async def capture() -> WorldSnapshot:
        return world

    monkeypatch.setattr("sim_pilot.cli.capture_openttd_world_snapshot", capture)
    runner = CliRunner()

    summary = runner.invoke(app, ["openttd", "world"])
    company = runner.invoke(app, ["openttd", "company"])
    payload = runner.invoke(app, ["openttd", "company", "--json"])
    help_result = runner.invoke(app, ["openttd", "--help"])

    assert summary.exit_code == 0, summary.output
    assert "Entities: 1 companies" in summary.output
    assert company.exit_code == 0, company.output
    assert "Fixture Transport" in company.output
    assert payload.exit_code == 0, payload.output
    assert '"cash": 425000' in payload.output
    for command in (
        "world",
        "towns",
        "industries",
        "stations",
        "vehicles",
        "company",
        "routes",
        "diff",
    ):
        assert command in help_result.output


def test_analysis_cli_uses_snapshot_files_without_action_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id="analysis-world",
            world_id="fixture-world",
            game="openttd",
            game_version="15.3",
            game_date=712223,
            capture_started_game_date=712223,
            capture_completed_game_date=712223,
            complete=True,
            capability_fingerprint="fingerprint",
            save_generation=2,
            bridge_sequence=4,
            captured_at=datetime.now(UTC),
            observer_company_id="company-1",
        ),
        coverage=(CapabilityCoverage(category="companies", status=CoverageStatus.AVAILABLE),),
        companies=(
            Company(
                id="company-1",
                name="Fixture Transport",
                cash=425000,
                loan=50000,
                income=1000,
                expenses=-2000,
            ),
        ),
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(world.model_dump_json(), encoding="utf-8")

    def unexpected(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("analysis must not initialize the action runtime")

    monkeypatch.setattr("sim_pilot.cli._runtime", unexpected)
    monkeypatch.setattr(
        "sim_pilot.cli.analysis_session_directory", lambda: tmp_path / "analysis-session"
    )
    runner = CliRunner()
    ask = runner.invoke(
        app,
        ["ask", "Why am I losing money?", "--snapshot", str(snapshot_path)],
    )
    direct = runner.invoke(
        app,
        ["openttd", "analyze", "company", "--snapshot", str(snapshot_path), "--json"],
    )

    assert ask.exit_code == 0, ask.output
    assert "Company Health" in ask.output
    assert "Negative operating result" in ask.output
    assert direct.exit_code == 0, direct.output
    assert '"analysis_type": "company_health"' in direct.output

    record = next((tmp_path / "analysis-session").glob("analysis-*.json"))
    analysis_id = json.loads(record.read_text(encoding="utf-8"))["analysis_id"]
    show = runner.invoke(app, ["analysis", "show", analysis_id])
    assert show.exit_code == 0, show.output
    assert "Negative operating result" in show.output
    finding_id = json.loads(record.read_text(encoding="utf-8"))["response"]["findings"][0][
        "finding_id"
    ]
    evidence = runner.invoke(app, ["analysis", "evidence", analysis_id, finding_id])
    entity = runner.invoke(app, ["analysis", "entity", analysis_id, "company", "C-001"])
    assert evidence.exit_code == 0, evidence.output
    assert "Evidence" in evidence.output
    assert entity.exit_code == 0, entity.output
    assert "Fixture Transport" in entity.output


def test_analysis_cli_requires_explicit_snapshot_or_live() -> None:
    result = CliRunner().invoke(app, ["openttd", "analyze", "company"])
    assert result.exit_code == INVALID_INPUT
    assert "supply --snapshot or explicitly select --live" in result.output


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
    assert '"world_snapshot": null' in result.output


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
