from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sim_pilot.cli import app
from sim_pilot.computer_control.errors import ComputerControlError
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.training import TrainingRecommendation
from sim_pilot.software_inc.ui.models import SoftwareIncUIAction
from tests.software_inc.guidance_helpers import guidance_context
from tests.software_inc.guidance_helpers import snapshot as guidance_snapshot
from tests.software_inc.test_guidance_service import service_for
from tests.software_inc.test_training import (  # pyright: ignore[reportPrivateUsage]
    _snapshot as training_snapshot,  # pyright: ignore[reportPrivateUsage]
)


def test_doctor_json_reports_exact_installation_without_gameplay_authority(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, game_root, _state = software_inc_installation

    def fixture_discovery() -> SoftwareIncDiscovery:
        return discovery

    monkeypatch.setattr("sim_pilot.cli._software_inc_discovery", fixture_discovery)

    result = CliRunner().invoke(app, ["software-inc", "doctor", "--json"])

    assert result.exit_code == 0
    assert '"steam_app_id": "362620"' in result.stdout
    assert f'"game_root": "{game_root}"' in result.stdout
    assert '"official_code_mod_api_observed": true' in result.stdout
    assert '"live_supported": false' in result.stdout
    assert "gameplay_actions" not in result.stdout


def test_doctor_returns_typed_failure_when_game_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    discovery = SoftwareIncDiscovery(steamapps=tmp_path / "empty")

    def fixture_discovery() -> SoftwareIncDiscovery:
        return discovery

    monkeypatch.setattr("sim_pilot.cli._software_inc_discovery", fixture_discovery)

    result = CliRunner().invoke(app, ["software-inc", "doctor"])

    assert result.exit_code == 25
    assert "Software Inc. is not installed." in result.stdout


def test_capabilities_reports_unified_authority_and_empty_semantic_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sim_pilot.cli._software_inc_guidance_service",
        lambda: service_for(guidance_context()),
    )
    result = CliRunner().invoke(app, ["software-inc", "capabilities"])

    assert result.exit_code == 0
    assert "Observation available: true" in result.stdout
    assert "Semantic gameplay actions: none" in result.stdout
    assert "Generic persisted-task runtime: unavailable" in result.stdout
    assert "create_team: offline_integration_tested" in result.stdout
    assert "pause: live_mutation_verified" in result.stdout


def test_guidance_direct_commands_share_services_and_support_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sim_pilot.cli._software_inc_guidance_service",
        lambda: service_for(guidance_context()),
    )
    runner = CliRunner()

    asked = runner.invoke(
        app,
        ["software-inc", "ask", "How many employees do I have?", "--json"],
    )
    course = runner.invoke(app, ["software-inc", "crash-course", "hiring"])
    testing = runner.invoke(app, ["software-inc", "crash-course", "--testing"])
    recommended = runner.invoke(app, ["software-inc", "recommend", "--json"])
    capabilities = runner.invoke(app, ["software-inc", "capabilities", "--json"])

    assert asked.exit_code == 0
    assert '"status": "answered"' in asked.stdout
    assert "You have 1 observed employee" in asked.stdout
    assert course.exit_code == 0
    assert "Software Inc. crash course — hiring" in course.stdout
    assert testing.exit_code == 0
    assert "installed_sha256=" in testing.stdout
    assert recommended.exit_code == 0
    assert '"rule_id": "review_empty_team"' in recommended.stdout
    assert capabilities.exit_code == 0
    assert '"semantic_gameplay_actions": []' in capabilities.stdout
    assert '"generic_task_runtime_available": false' in capabilities.stdout


def test_interactive_teacher_advisor_and_blocked_operator_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sim_pilot.cli._software_inc_guidance_service",
        lambda: service_for(guidance_context()),
    )

    result = CliRunner().invoke(
        app,
        ["software-inc", "play"],
        input=(
            "/crash_course teams\n"
            "How many employees do I have?\n"
            "/recommend\n"
            "/why\n"
            "/operate hire one programmer for Support Alpha for no more than $8,000 per month\n"
            "maybe help with staffing\n"
            "/quit\n"
        ),
    )

    assert result.exit_code == 0
    assert "Software Inc. crash course — teams" in result.stdout
    assert "You have 1 observed employee" in result.stdout
    assert "Recommended: Review staffing for Support Alpha" in result.stdout
    assert "Rule review_empty_team matched" in result.stdout
    assert "live mutation gate is pending" in result.stdout
    assert "could not safely distinguish a question from an action" in result.stdout


def test_interactive_session_routes_exact_workstation_to_approval_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    async def execute(instruction: str, *, dry_run: bool) -> SimpleNamespace:
        calls.append((instruction, dry_run))
        return SimpleNamespace(
            intent=SimpleNamespace(action=SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION),
            verified=True,
            gestures_sent=7,
            cycles=8,
            message="Prepared one verified workstation for Core.",
        )

    monkeypatch.setattr("sim_pilot.cli._execute_software_inc_workstation", execute)
    result = CliRunner().invoke(
        app,
        ["software-inc", "play"],
        input="/operate prepare one workstation for Core\n/quit\n",
    )

    assert result.exit_code == 0
    assert "Prepared one verified workstation for Core." in result.stdout
    assert calls == [("prepare one workstation for Core", False)]


def test_bridge_install_requires_explicit_broad_access_option(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    discovery, _game_root, _state = software_inc_installation

    monkeypatch.setattr("sim_pilot.cli._software_inc_discovery", lambda: discovery)
    monkeypatch.setattr(
        "sim_pilot.cli._software_inc_bridge_installer",
        lambda: __import__(
            "sim_pilot.software_inc.bridge.installer", fromlist=["SoftwareIncBridgeInstaller"]
        ).SoftwareIncBridgeInstaller(
            discovery=discovery,
            artifact=tmp_path / "missing.dll",
            state_directory=tmp_path / "bridge-state",
        ),
    )

    result = CliRunner().invoke(app, ["software-inc", "bridge", "install"])

    assert result.exit_code == 25
    assert "--approve-broad-access" in result.stderr


def test_probe_source_retains_least_authority_contract() -> None:
    source = Path("software_inc_bridge/probe/SimPilotDiscoveryProbe.cs").read_text(encoding="utf-8")

    assert "OnActivate" in source
    assert "ConstructOptionsScreen" in source
    assert "GameSettings.GameReady" in source
    assert "GiveMeFreedom" not in source
    assert "Serialize(" not in source
    assert "Deserialize(" not in source
    assert "Tcp" not in source


def test_semantic_bridge_source_is_read_only_and_main_thread_handed_off() -> None:
    source = Path("software_inc_bridge/bridge/SimPilotSoftwareIncBridge.cs").read_text(
        encoding="utf-8"
    )

    assert "GiveMeFreedom = true" in source
    assert 'new GameObject("Sim Pilot Capture Pump")' in source
    assert "DontDestroyOnLoad(pumpObject)" in source
    assert "AddComponent<SimPilotCapturePump>" in source
    assert "event=pump_started" in source
    assert "Application.runInBackground" not in source
    assert "provider.ProcessPendingCapture()" in source
    assert "AssertMainThread" in source
    assert "ManualResetEvent" in source
    assert '"Library", "Application Support", "Sim Pilot"' in source
    assert "SpecialFolder.ApplicationData" not in source
    assert "IPAddress.Any" not in source
    assert "Serialize(" not in source
    assert "Deserialize(" not in source
    assert "var completionWindowDays = work.Months * GameSettings.DaysPerMonth;" in source
    assert '["deadline"] = JsonValue.String(relativeDeadline)' in source
    assert '["days_remaining"] = JsonValue.Number(completionWindowDays)' in source
    assert "private static JsonValue SafeString(string? value)" in source
    assert '["contract_deadline_observed"] = JsonValue.Boolean(' in source
    assert 'contractDeadline.IndexOf("1900", StringComparison.Ordinal) < 0' in source
    assert '"software-inc-readonly-v10"' in source
    assert "surfaces.Add(EducationSurface(settings))" in source
    assert "surfaces.Add(EducationUiSurface())" in source
    assert "JsonValue.Integer(EducationWindow.EducationMonths)" in source
    assert "JsonValue.Number(EducationWindow.GetEducationCost(pair.Value))" in source
    assert '["category"] = SafeString(item.GetCategory())' in source
    assert '["name"] = SafeString(item.Name)' in source
    assert '["stage"] = SafeString(item.GetCurrentStage())' in source
    assert '["work_type"] = SafeString(item.GetWorkTypeName())' in source
    for mutation in (
        "Hire(",
        "Fire(",
        "Buy(",
        "Sell(",
        "Save(",
        "SetGameSpeed",
        ".SendEm(",
    ):
        assert mutation not in source


def test_compiled_bridge_targets_unity_mono_not_netstandard() -> None:
    project = Path("software_inc_bridge/bridge/SimPilotSoftwareIncBridge.csproj").read_text(
        encoding="utf-8"
    )

    assert "<TargetFramework>net472</TargetFramework>" in project
    assert "netstandard" not in project.casefold()


def test_task_commands_fail_before_compiling_or_persisting_software_inc() -> None:
    runner = CliRunner()

    compiled = runner.invoke(
        app,
        [
            "task",
            "compile",
            "--adapter",
            "software_inc",
            "--instruction",
            "hire another developer",
        ],
    )
    created = runner.invoke(app, ["task", "create", "--adapter", "software_inc"])

    assert compiled.exit_code == 20
    assert created.exit_code == 20
    assert "generic persisted-task runtime is unavailable" in compiled.stderr.casefold()
    assert "generic persisted-task runtime is unavailable" in created.stderr.casefold()


def test_ui_do_rejects_unsupported_plain_english_before_observation() -> None:
    result = CliRunner().invoke(app, ["software-inc", "ui", "do", "hire ten developers"])

    assert result.exit_code == 25
    assert "explicit USD monthly salary cap" in result.stderr


def test_office_readiness_command_reports_capacity_without_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def observe_fixture():
        return guidance_snapshot()

    monkeypatch.setattr("sim_pilot.cli._software_inc_bridge_observe_async", observe_fixture)

    result = CliRunner().invoke(app, ["software-inc", "office", "readiness", "Core"])

    assert result.exit_code == 0
    assert "Core: capacity 1/1; working hours 8-16." in result.stdout
    assert "universal source-control prerequisite=false" in result.stdout


def test_contract_command_reports_computer_control_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def browse_fixture(*, dry_run: bool):
        del dry_run
        raise ComputerControlError("select a fitting resolution")

    monkeypatch.setattr("sim_pilot.cli.browse_contracts", browse_fixture)

    result = CliRunner().invoke(
        app,
        ["software-inc", "contracts", "do", "browse contracts"],
    )

    assert result.exit_code == 25
    assert result.exception is not None
    assert "error[ComputerControlError]: select a fitting resolution" in result.stderr
    assert "Traceback" not in result.stderr


def test_training_terminal_recommends_and_routes_exact_plain_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def observe_fixture():
        return training_snapshot(10)

    calls: list[tuple[str, Decimal, bool]] = []

    async def start_fixture(
        recommendation: TrainingRecommendation | None,
        *,
        approval_provider: object,
        dry_run: bool,
        existing_workflow: object,
    ) -> SimpleNamespace:
        del approval_provider, existing_workflow
        assert recommendation is not None
        assert recommendation.recommended is not None
        calls.append(
            (
                recommendation.team_name,
                recommendation.recommended.minimum_cash_reserve,
                dry_run,
            )
        )
        return SimpleNamespace(message="Dry run: exact Education plan is ready.")

    monkeypatch.setattr("sim_pilot.cli._software_inc_bridge_observe_async", observe_fixture)
    monkeypatch.setattr("sim_pilot.cli.start_training", start_fixture)
    runner = CliRunner()

    recommendation = runner.invoke(
        app,
        [
            "software-inc",
            "training",
            "recommend",
            "--team",
            "Core",
            "--minimum-cash-reserve",
            "50000",
        ],
    )
    start = runner.invoke(
        app,
        [
            "software-inc",
            "training",
            "do",
            "train one suitable employee from Core in System design for three months while "
            "keeping $50,000 in cash",
            "--dry-run",
        ],
    )

    assert recommendation.exit_code == 0
    assert (
        "Designer/System level 0 -> 3, three sequential one-month courses, "
        "projected direct cost $7,600.00" in recommendation.stdout
    )
    assert start.exit_code == 0
    assert "exact Education plan is ready" in start.stdout
    assert calls == [("Core", Decimal("50000"), True)]
