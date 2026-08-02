"""Process-facing CLI for durable tasks, providers, recovery, and OpenTTD."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal, NoReturn
from uuid import UUID, uuid4

import typer
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine

from sim_pilot.adapter_registry import adapter_registration
from sim_pilot.adapters.base import AdapterSnapshot, SimulationAdapter
from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSnapshotMetadata,
    AnalysisSubjectType,
    AnalysisType,
    DeterministicAnalysisCompiler,
)
from sim_pilot.analysis.compiler import (
    AnalysisCompilation,
    AnalysisCompiler,
)
from sim_pilot.analysis.contracts import SnapshotSource
from sim_pilot.analysis.entity_inspection import (
    EntityInspectionError,
    evaluate_unsupported_inspection,
    render_inspection_result,
    resolve_inspection_action,
)
from sim_pilot.analysis.errors import AnalysisError
from sim_pilot.analysis.evidence_view import (
    render_entity,
    render_finding_evidence,
    render_session_summary,
)
from sim_pilot.analysis.explanation import ExplanationProvider, ExplanationStyle
from sim_pilot.analysis.freshness import (
    SnapshotCache,
    SnapshotCacheStatus,
    SnapshotIdentity,
    SnapshotVerification,
)
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.progress import AnalysisProgress
from sim_pilot.analysis.query import AnalysisQueryService
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionRecord, AnalysisSessionStore
from sim_pilot.analysis_provider import (
    CodexAnalysisCompiler,
    CodexExplanationProvider,
    OpenAIAnalysisCompiler,
    OpenAIExplanationProvider,
)
from sim_pilot.computer_control.errors import ComputerControlError
from sim_pilot.config import (
    analysis_session_directory,
    codex_capability_cache_seconds,
    codex_executable,
    codex_maximum_stderr_bytes,
    codex_maximum_stdout_bytes,
    codex_model,
    codex_preserve_debug_directory,
    codex_temporary_directory_root,
    codex_timeout_seconds,
    compiler_model,
    database_url,
    decision_model,
    decision_timeout_seconds,
)
from sim_pilot.decision_provider import (
    CodexCLIDecisionProvider,
    OpenAIDecisionProvider,
    RecordingDecisionProvider,
)
from sim_pilot.domain import (
    Action,
    AdapterId,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    Observation,
    Task,
    TaskSpecification,
    TaskStatus,
    WorldSnapshot,
)
from sim_pilot.domain.models import JsonValue
from sim_pilot.game_bridge import GameBridgeError, GameSnapshot
from sim_pilot.guidance import (
    DelegationResult,
    GuidanceStatus,
    InteractionKind,
    RecommendationResponse,
)
from sim_pilot.intent_compiler import (
    CompilerError,
    CompilerProvider,
    IntentCompiler,
    ValidationStatus,
)
from sim_pilot.intent_compiler.prompt import (
    capability_catalog,
    compiler_prompt,
)
from sim_pilot.intent_compiler.providers import (
    CodexCLICompilerProvider,
    NoProviderConfigured,
    OpenAICompilerProvider,
    RecordingCompilerProvider,
)
from sim_pilot.openttd import (
    OpenTTDAdapterCapabilities,
    OpenTTDAdminClient,
    OpenTTDError,
    OpenTTDObservationState,
    openttd_configuration,
)
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.models import BridgeHealth
from sim_pilot.openttd.query_output import (
    render_world_changes,
    render_world_collection,
    render_world_summary,
)
from sim_pilot.openttd.world_translation import canonical_entity_id
from sim_pilot.persistence import PersistenceError
from sim_pilot.persistence.sqlite import (
    SQLiteUnitOfWork,
    create_sqlite_engine,
    upgrade_database,
)
from sim_pilot.product_evaluation import (
    EvaluationRunConfiguration,
    ProductEvaluationCase,
    run_product_evaluation,
)
from sim_pilot.provider_metadata import ProviderMetadata
from sim_pilot.provider_support.codex_cli.errors import CodexCLIError
from sim_pilot.rail_route import (
    RailRouteAction,
    RailRouteController,
    RailRouteDiscovery,
    parse_control_intent,
)
from sim_pilot.rail_route.bridge import (
    RailRouteBridgeError,
    RailRouteBridgeInstaller,
    entity_from,
    prove_read_only_bridge,
    rail_route_bridge_client,
    surface_from,
)
from sim_pilot.rail_route.bridge import (
    render_entity as render_rail_route_entity,
)
from sim_pilot.rail_route.bridge import (
    render_surface as render_rail_route_surface,
)
from sim_pilot.rail_route.errors import RailRouteError
from sim_pilot.rail_route.ui import RailRouteUIObserver, append_ui_trace, execute_set_route_ui
from sim_pilot.reconciliation import default_reconciliation_dispatcher
from sim_pilot.runtime import RuntimeEngine
from sim_pilot.runtime.action_attempts import RecoveryResolution
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
from sim_pilot.runtime.decision_errors import (
    DecisionProviderError,
    DecisionProviderNotConfiguredError,
)
from sim_pilot.runtime.errors import DurablePersistenceError, ReconstructionConsistencyError
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.reconstruction import ReconstructedRuntimeContext
from sim_pilot.runtime.verification import ActionVerifier
from sim_pilot.software_inc import (
    SoftwareIncBridgeInstaller,
    SoftwareIncDiscovery,
    SoftwareIncError,
    SoftwareIncProbeInstaller,
)
from sim_pilot.software_inc.bridge import (
    entity_from as software_inc_entity_from,
)
from sim_pilot.software_inc.bridge import (
    prove_read_only_bridge as prove_software_inc_read_only_bridge,
)
from sim_pilot.software_inc.bridge import (
    render_entity as render_software_inc_entity,
)
from sim_pilot.software_inc.bridge import (
    render_surface as render_software_inc_surface,
)
from sim_pilot.software_inc.bridge import (
    software_inc_bridge_client,
)
from sim_pilot.software_inc.bridge import (
    surface_from as software_inc_surface_from,
)
from sim_pilot.software_inc.contracts.intent import ContractIntentAction, parse_contract_intent
from sim_pilot.software_inc.contracts.models import ContractApproval, ContractRecommendation
from sim_pilot.software_inc.contracts.operator import (
    accept_recommended_contract,
    advance_contract,
    browse_contracts,
    promote_contract,
    release_contract,
    review_contract,
)
from sim_pilot.software_inc.contracts.policy import recommend_contracts
from sim_pilot.software_inc.contracts.projection import active_contract_work, available_contracts
from sim_pilot.software_inc.contracts.store import ContractWorkflowStore
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError
from sim_pilot.software_inc.guidance import (
    SoftwareIncGuidanceService,
    classify_interaction,
    render_guidance,
)
from sim_pilot.software_inc.products import (
    ProductApproval,
    ProductIntentAction,
    ProductOperationResult,
    ProductRecommendation,
    ProductWorkflow,
    ProductWorkflowStore,
    advance_product,
    close_product_configuration,
    iterate_product,
    operating_system_options,
    parse_product_intent,
    product_features,
    product_type,
    promote_product,
    recommend_atlas,
    review_product,
    set_product_hold,
    start_atlas,
)
from sim_pilot.software_inc.products.contract import ATLAS_PRODUCT_TYPE
from sim_pilot.software_inc.products.projection import product_ui_state, product_work
from sim_pilot.software_inc.training import (
    TrainingApproval,
    TrainingIntentAction,
    TrainingRecommendation,
    TrainingWorkflow,
    advance_training,
    exact_employee_training,
    parse_training_intent,
    recommend_training,
    start_training,
)
from sim_pilot.software_inc.training.store import TrainingWorkflowStore
from sim_pilot.software_inc.ui import (
    SoftwareIncUIObserver,
    StaffingApproval,
    StaffingPlan,
    WorkstationOperationResult,
    WorkstationPlan,
    execute_office_intent,
    execute_staffing_intent,
    execute_workstation_intent,
    parse_office_intent,
    parse_staffing_intent,
    parse_workstation_intent,
    project_team_readiness,
)
from sim_pilot.software_inc.ui import (
    diagnose_ui as diagnose_software_inc_ui,
)
from sim_pilot.software_inc.ui import (
    execute_ui_action as execute_software_inc_ui_action,
)
from sim_pilot.software_inc.ui import (
    parse_ui_action as parse_software_inc_ui_action,
)

SUCCESS = 0
WAITING_APPROVAL = 10
RECOVERY_REQUIRED = 11
BLOCKED = 12
FAILED = 13
CANCELLED = 14
INVALID_INPUT = 20
PERSISTENCE_FAILURE = 21
MIGRATION_FAILURE = 22
OPENTTD_FAILURE = 23
RAIL_ROUTE_FAILURE = 24
SOFTWARE_INC_FAILURE = 25

app = typer.Typer(help="Durable local runtime for the deterministic reference simulation.")
db_app = typer.Typer(help="Manage durable schema state.")
task_app = typer.Typer(help="Create and operate structured tasks.")
recovery_app = typer.Typer(help="Inspect and resolve interrupted action attempts.")
openttd_app = typer.Typer(help="Observe a local OpenTTD 15.3 game through its admin port.")
openttd_analyze_app = typer.Typer(help="Run deterministic read-only gameplay analysis.")
analysis_app = typer.Typer(help="Inspect previous gameplay analysis and evidence.")
openttd_action_app = typer.Typer(help="Run a directly validated and verified OpenTTD action.")
openttd_bridge_app = typer.Typer(help="Operate the versioned OpenTTD GameScript bridge.")
openttd_bridge_action_app = typer.Typer(help="Run a verified, explicitly enabled bridge action.")
evaluate_app = typer.Typer(help="Run explicitly authorized product evaluation exercises.")
rail_route_app = typer.Typer(help="Control a local Rail Route game with verified plain English.")
rail_route_bridge_app = typer.Typer(help="Operate the read-only Rail Route semantic bridge.")
rail_route_ui_app = typer.Typer(help="Diagnose synchronized Rail Route UI control.")
software_inc_app = typer.Typer(help="Inspect the frozen Software Inc. reference integration.")
software_inc_probe_app = typer.Typer(help="Manage the reversible official code-mod probe.")
software_inc_bridge_app = typer.Typer(help="Operate the read-only Software Inc. semantic bridge.")
software_inc_ui_app = typer.Typer(help="Operate verified Software Inc. visible-UI control.")
software_inc_office_app = typer.Typer(help="Inspect and configure Software Inc. office readiness.")
software_inc_contracts_app = typer.Typer(
    help="Recommend and operate one verified Software Inc. contract."
)
software_inc_training_app = typer.Typer(
    help="Recommend and operate one verified Software Inc. education assignment."
)
software_inc_products_app = typer.Typer(
    help="Recommend and operate the controlled Prompt 7 Atlas product lifecycle."
)
app.add_typer(db_app, name="db")
app.add_typer(task_app, name="task")
app.add_typer(openttd_app, name="openttd")
app.add_typer(analysis_app, name="analysis")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(rail_route_app, name="rail-route")
app.add_typer(software_inc_app, name="software-inc")
rail_route_app.add_typer(rail_route_bridge_app, name="bridge")
rail_route_app.add_typer(rail_route_ui_app, name="ui")
software_inc_app.add_typer(software_inc_probe_app, name="probe")
software_inc_app.add_typer(software_inc_bridge_app, name="bridge")
software_inc_app.add_typer(software_inc_ui_app, name="ui")
software_inc_app.add_typer(software_inc_office_app, name="office")
software_inc_app.add_typer(software_inc_contracts_app, name="contracts")
software_inc_app.add_typer(software_inc_training_app, name="training")
software_inc_app.add_typer(software_inc_products_app, name="products")
openttd_app.add_typer(openttd_action_app, name="action")
openttd_app.add_typer(openttd_analyze_app, name="analyze")
openttd_app.add_typer(openttd_bridge_app, name="bridge")
openttd_bridge_app.add_typer(openttd_bridge_action_app, name="action")
task_app.add_typer(recovery_app, name="recovery")

DEFAULT_PRODUCT_EVALUATION_FIXTURE = Path("tests/fixtures/product_evaluation_instructions.json")
PRODUCT_EVALUATION_MAX_OUTPUT_TOKENS = 2048
DEFAULT_ANALYSIS_MAXIMUM_SNAPSHOT_AGE_SECONDS = 5.0


@dataclass
class CLIContext:
    url: str


@dataclass(frozen=True)
class AnalysisSnapshotAcquisition:
    snapshot: WorldSnapshot
    source: SnapshotSource
    maximum_acceptable_age_seconds: float | None
    collection_duration_seconds: float | None
    verification: SnapshotVerification | None = None
    bridge_supported_actions: tuple[str, ...] = ()

    def metadata(self, *, now: datetime | None = None) -> AnalysisSnapshotMetadata:
        instant = now or datetime.now(UTC)
        source = self.snapshot.metadata
        verification = self.verification
        return AnalysisSnapshotMetadata(
            source=self.source,
            snapshot_age_seconds=max(0.0, (instant - source.captured_at).total_seconds()),
            maximum_acceptable_age_seconds=self.maximum_acceptable_age_seconds,
            collection_duration_seconds=self.collection_duration_seconds,
            collection_interval_game_days=(
                source.capture_completed_game_date - source.capture_started_game_date
            ),
            world_id=source.world_id,
            observer_company_id=source.observer_company_id,
            bridge_company_context=(
                None if verification is None else verification.identity.bridge_company_context
            ),
            save_generation=source.save_generation,
            capability_fingerprint=source.capability_fingerprint,
            snapshot_bridge_sequence=source.bridge_sequence,
            identity_verification_sequence=(
                None if verification is None else verification.bridge_sequence
            ),
            identity_verified_at=(None if verification is None else verification.verified_at),
            bridge_synchronization_state=(
                "snapshot_metadata_only"
                if verification is None
                else verification.synchronization_state
            ),
            openttd_version=(
                source.game_version if verification is None else verification.openttd_version
            ),
            bridge_protocol_version=(
                None if verification is None else verification.bridge_protocol_version
            ),
            bridge_script_version=(None if verification is None else verification.script_version),
        )


class CompilerProviderName(StrEnum):
    NONE = "none"
    OPENAI = "openai"
    CODEX = "codex"


class DecisionProviderName(StrEnum):
    NONE = "none"
    SCRIPTED = "scripted"
    OPENAI = "openai"
    CODEX = "codex"


class AnalysisProviderName(StrEnum):
    NONE = "none"
    OPENAI = "openai"
    CODEX = "codex"


@app.callback()
def main(
    ctx: typer.Context,
    database: Annotated[
        str | None,
        typer.Option("--database", help="SQLite URL or database file path."),
    ] = None,
) -> None:
    ctx.obj = CLIContext(database_url(database))


def _context(ctx: typer.Context) -> CLIContext:
    return ctx.ensure_object(CLIContext)


def _runtime(ctx: typer.Context) -> tuple[Engine, RuntimeEngine]:
    engine = create_sqlite_engine(_context(ctx).url)
    return engine, RuntimeEngine(
        unit_of_work_factory=lambda: SQLiteUnitOfWork(engine),
        reconciliation_dispatcher=default_reconciliation_dispatcher(),
    )


def _intent_compiler(
    provider_name: CompilerProviderName,
    recording_directory: Path | None,
    adapter_name: AdapterId = AdapterId.REFERENCE,
    model_name: str | None = None,
) -> IntentCompiler:
    registration = adapter_registration(adapter_name)
    if not registration.compiler_available:
        raise ValueError(
            registration.unavailable_reason
            or f"intent compilation is unavailable for {adapter_name.value!r}"
        )
    catalog = capability_catalog(adapter_name.value)
    prompt = compiler_prompt(catalog)
    provider: CompilerProvider
    if provider_name is CompilerProviderName.OPENAI:
        provider = OpenAICompilerProvider(model=compiler_model(model_name), prompt=prompt)
    elif provider_name is CompilerProviderName.CODEX:
        provider = CodexCLICompilerProvider(
            model=codex_model(model_name),
            prompt=prompt,
            timeout_seconds=codex_timeout_seconds(),
            executable=codex_executable(),
            temporary_directory_root=codex_temporary_directory_root(),
            preserve_debug_directory=codex_preserve_debug_directory(),
            maximum_stdout_bytes=codex_maximum_stdout_bytes(),
            maximum_stderr_bytes=codex_maximum_stderr_bytes(),
            capability_cache_seconds=codex_capability_cache_seconds(),
        )
    elif provider_name is CompilerProviderName.NONE:
        provider = NoProviderConfigured()
    else:
        raise ValueError(f"unsupported compiler provider: {provider_name!r}")
    if recording_directory is not None:
        provider = RecordingCompilerProvider(provider, recording_directory, prompt=prompt)
    return IntentCompiler(provider, catalog)


def _restore(context: ReconstructedRuntimeContext) -> SimulationAdapter:
    adapter_type = context.task.specification.adapter_type
    registration = adapter_registration(adapter_type)
    if not registration.runtime_factory_available:
        raise ReconstructionConsistencyError(
            registration.unavailable_reason
            or f"runtime factory is unavailable for {registration.adapter_id.value!r}"
        )
    if adapter_type is AdapterId.OPENTTD:
        prior_health: BridgeHealth | None = None
        if context.checkpoint is not None:
            raw = context.checkpoint.state.get("bridge")
            if isinstance(raw, dict):
                prior_health = BridgeHealth.model_validate(raw, strict=True)
        return _openttd_adapter(
            prior_bridge_health=prior_health,
            reject_bridge_identity_change=prior_health is not None,
        )
    if adapter_type is AdapterId.REFERENCE:
        if context.checkpoint is None:
            return ReferenceSimulationAdapter()
        return ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot())
    raise ReconstructionConsistencyError(f"unsupported adapter type: {adapter_type.value!r}")


class ReferenceDemoDecisionProvider:
    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        action_type = "advance_time"
        parameters: dict[str, JsonValue] = {"ticks": 1}
        expected_effect = "Advance one simulation tick."
        resource = context.specification.objective.parameters.get("resource")
        if resource in {"server_name", "company_name"}:
            target = context.specification.objective.parameters.get("target")
            if not isinstance(target, str):
                raise DecisionProviderNotConfiguredError(
                    f"scripted OpenTTD decision requires a string {resource} target"
                )
            action_type = "set_company_name" if resource == "company_name" else "set_server_name"
            if not any(action.type == action_type for action in context.available_actions):
                raise DecisionProviderNotConfiguredError(
                    f"scripted OpenTTD decision requires advertised {action_type}"
                )
            parameters = {"name": target}
            expected_effect = f"Set the observed OpenTTD server name to {target!r}."
        return DecisionProviderResult(
            decision=Decision(
                type=DecisionType.EXECUTE,
                reason=f"Execute the advertised {action_type} action.",
                action=Action(
                    type=action_type,
                    parameters=parameters,
                    expected_effect=expected_effect,
                ),
            ),
            metadata=ProviderMetadata(
                provider="scripted",
                prompt_version="decision-provider-v1",
                validation_result="scripted",
            ),
        )


def _decision_provider(
    provider_name: DecisionProviderName,
    recording_directory: Path | None,
    model_name: str | None = None,
) -> DecisionProvider:
    provider: DecisionProvider
    if provider_name is DecisionProviderName.NONE:
        raise DecisionProviderNotConfiguredError(
            "no decision provider configured; select --decision-provider codex, openai, or scripted"
        )
    if provider_name is DecisionProviderName.OPENAI:
        provider = OpenAIDecisionProvider(
            model=decision_model(model_name),
            timeout_seconds=decision_timeout_seconds(),
        )
    elif provider_name is DecisionProviderName.CODEX:
        provider = CodexCLIDecisionProvider(
            model=codex_model(model_name),
            timeout_seconds=codex_timeout_seconds(),
            executable=codex_executable(),
            temporary_directory_root=codex_temporary_directory_root(),
            preserve_debug_directory=codex_preserve_debug_directory(),
            maximum_stdout_bytes=codex_maximum_stdout_bytes(),
            maximum_stderr_bytes=codex_maximum_stderr_bytes(),
            capability_cache_seconds=codex_capability_cache_seconds(),
        )
    elif provider_name is DecisionProviderName.SCRIPTED:
        provider = ReferenceDemoDecisionProvider()
    else:
        raise ValueError(f"unsupported decision provider: {provider_name!r}")
    if recording_directory is not None:
        provider = RecordingDecisionProvider(provider, recording_directory)
    return provider


def _exit_for(status: TaskStatus, recovery: bool = False) -> int:
    if recovery:
        return RECOVERY_REQUIRED
    return {
        TaskStatus.WAITING_FOR_APPROVAL: WAITING_APPROVAL,
        TaskStatus.BLOCKED: BLOCKED,
        TaskStatus.FAILED: FAILED,
        TaskStatus.CANCELLED: CANCELLED,
    }.get(status, SUCCESS)


def _emit(value: object) -> None:
    if isinstance(value, BaseModel):
        typer.echo(value.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(value, indent=2, default=str))


def _fail(error: Exception, code: int = PERSISTENCE_FAILURE) -> NoReturn:
    typer.echo(f"error[{type(error).__name__}]: {error}", err=True)
    raise typer.Exit(code)


def _rail_route_controller() -> RailRouteController:
    return RailRouteController()


def _software_inc_discovery() -> SoftwareIncDiscovery:
    return SoftwareIncDiscovery()


def _software_inc_probe_installer() -> SoftwareIncProbeInstaller:
    return SoftwareIncProbeInstaller(discovery=_software_inc_discovery())


def _software_inc_bridge_installer() -> SoftwareIncBridgeInstaller:
    return SoftwareIncBridgeInstaller(discovery=_software_inc_discovery())


def _software_inc_guidance_service() -> SoftwareIncGuidanceService:
    return SoftwareIncGuidanceService()


@software_inc_app.command("doctor")
def software_inc_doctor(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete strict discovery result.")
    ] = False,
) -> None:
    """Inspect Software Inc. without changing its installation or saves."""
    try:
        result = _software_inc_discovery().inspect()
        if json_output:
            _emit(result)
        elif not result.installed:
            typer.echo("Software Inc. is not installed.")
            typer.echo(result.reasons[0])
        else:
            version = result.product_version or "unknown version"
            state = "running" if result.running else "not running"
            support = "live-proven" if result.live_supported else "not live-proven"
            typer.echo(f"Software Inc. {version} detected; {state}; {support}.")
            if result.reasons:
                typer.echo("Blocking reasons: " + "; ".join(result.reasons))
            if result.warnings:
                typer.echo("Warnings: " + "; ".join(result.warnings))
        if not result.installed:
            raise typer.Exit(SOFTWARE_INC_FAILURE)
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_app.command("capabilities")
def software_inc_capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print unified semantic, direct-UI, knowledge, and runtime evidence."""
    try:
        result = asyncio.run(_software_inc_guidance_service().capabilities())
        _emit(result) if json_output else typer.echo(render_guidance(result))
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_app.command("ask")
def software_inc_ask(
    question: Annotated[str, typer.Argument(help="Read-only Software Inc. question.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Answer from observed state and versioned repository knowledge without UI input."""
    try:
        result = asyncio.run(_software_inc_guidance_service().ask(question))
        _emit(result) if json_output else typer.echo(render_guidance(result))
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_app.command("crash-course")
def software_inc_crash_course(
    topic: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional topic: company, teams, hiring, office, schedules, roles, servers, "
                "contracts, products, development, "
                "or capabilities."
            )
        ),
    ] = None,
    testing: Annotated[
        bool,
        typer.Option("--testing", help="Show exact live/offline development evidence."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Teach the verified basics, personalized when compatible state is available."""
    try:
        result = asyncio.run(
            _software_inc_guidance_service().crash_course(
                topic or "company",
                testing=testing,
            )
        )
        _emit(result) if json_output else typer.echo(render_guidance(result))
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_app.command("recommend")
def software_inc_recommend(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Recommend one evidence-grounded objective without executing it."""
    try:
        result = asyncio.run(_software_inc_guidance_service().recommend())
        _emit(result) if json_output else typer.echo(render_guidance(result))
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


_SOFTWARE_INC_PLAY_HELP = """Commands:
  /crash_course [company|teams|hiring|office|schedules|roles|servers|contracts]
                [training|products|development|capabilities|testing]
  /status
  /recommend
  /why
  /capabilities
  /operate <objective>
  /help
  /quit
Plain-English questions are always read-only. Only /operate or an unambiguous
imperative can delegate a currently live-proven action."""


@software_inc_app.command("play")
def software_inc_play(
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Preauthorize each exact freshly rebound Atlas commitment (sandbox only).",
        ),
    ] = False,
) -> None:
    """Run the Software Inc. teacher, advisor, and bounded operator session."""
    service = _software_inc_guidance_service()
    current_recommendation: RecommendationResponse | None = None
    typer.echo("Sim Pilot Software Inc. — teacher, advisor, and bounded operator")
    typer.echo("Try /crash_course, ask a question, or type /help.")
    while True:
        try:
            instruction = typer.prompt("software-inc")
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            return
        route = classify_interaction(instruction)
        if route.kind is InteractionKind.QUIT:
            return
        if route.kind is InteractionKind.HELP:
            typer.echo(_SOFTWARE_INC_PLAY_HELP)
            continue
        try:
            result: BaseModel
            if route.kind is InteractionKind.QUESTION:
                result = asyncio.run(service.ask(instruction))
            elif route.kind is InteractionKind.CRASH_COURSE:
                result = asyncio.run(
                    service.crash_course(
                        route.topic or "company",
                        testing=route.topic == "testing",
                    )
                )
            elif route.kind is InteractionKind.STATUS:
                result = asyncio.run(service.status())
            elif route.kind is InteractionKind.RECOMMENDATION:
                current_recommendation = asyncio.run(service.recommend())
                result = current_recommendation
            elif route.kind is InteractionKind.EXPLANATION:
                result = asyncio.run(service.explain(current_recommendation))
            elif route.kind is InteractionKind.CAPABILITIES:
                result = asyncio.run(service.capabilities())
            elif route.kind is InteractionKind.DELEGATION and not route.clarification_required:
                assert route.objective is not None
                if "atlas" in route.objective.casefold():
                    product_intent = parse_product_intent(route.objective)
                    if product_intent.mapping_note:
                        typer.echo("Version mapping: " + product_intent.mapping_note)
                    if product_intent.action is ProductIntentAction.CREATE:
                        product_result = asyncio.run(
                            start_atlas(
                                minimum_cash_reserve=product_intent.minimum_cash_reserve,
                                approval_provider=_product_approval_provider(yes),
                            )
                        )
                    else:
                        product_snapshot = asyncio.run(_software_inc_bridge_observe_async())
                        if product_intent.action is ProductIntentAction.STATUS:
                            product_workflow = _current_product_workflow(
                                product_snapshot, include_completed=True
                            )
                            typer.echo(
                                f"Atlas is {product_workflow.stage.value}; progress "
                                f"{product_workflow.progress:g}; "
                                f"held={product_workflow.held}."
                            )
                            continue
                        product_result = _run_product_action(
                            product_intent.action,
                            product_snapshot,
                            seconds=10.0,
                            dry_run=False,
                            auto_approve=yes,
                        )
                    result = DelegationResult(
                        status=(
                            GuidanceStatus.COMPLETED
                            if product_result.verified
                            else GuidanceStatus.BLOCKED
                        ),
                        objective=route.objective,
                        action=product_intent.action.value,
                        gestures_sent=product_result.gestures_sent,
                        verified=product_result.verified,
                        message=product_result.message,
                    )
                elif (
                    "system design" in route.objective.casefold()
                    or "education" in route.objective.casefold()
                ):
                    training_intent = parse_training_intent(route.objective)
                    if (
                        training_intent.action is not TrainingIntentAction.START
                        or training_intent.team_name is None
                        or training_intent.minimum_cash_reserve is None
                    ):
                        raise SoftwareIncUIValidationError(
                            "interactive education delegation must name the team, System design, "
                            "three months, and a cash reserve"
                        )
                    training_snapshot = asyncio.run(_software_inc_bridge_observe_async())
                    training_save_identity = json.dumps(
                        training_snapshot.save_identity.model_dump(mode="json"), sort_keys=True
                    )
                    training_existing = TrainingWorkflowStore().current(
                        game_session_id=training_snapshot.game_session_id,
                        save_identity=training_save_identity,
                    )
                    training_recommendation = (
                        None
                        if training_existing is not None
                        else recommend_training(
                            training_snapshot,
                            team_name=training_intent.team_name,
                            minimum_cash_reserve=training_intent.minimum_cash_reserve,
                        )
                    )
                    training_result = asyncio.run(
                        start_training(
                            training_recommendation,
                            approval_provider=_training_approval,
                            existing_workflow=training_existing,
                        )
                    )
                    result = DelegationResult(
                        status=(
                            GuidanceStatus.COMPLETED
                            if training_result.verified
                            else GuidanceStatus.BLOCKED
                        ),
                        objective=route.objective,
                        action="start_education",
                        gestures_sent=training_result.gestures_sent,
                        verified=training_result.verified,
                        message=training_result.message,
                    )
                elif "workstation" in route.objective.casefold():
                    workstation = asyncio.run(
                        _execute_software_inc_workstation(route.objective, dry_run=False)
                    )
                    result = DelegationResult(
                        status=(
                            GuidanceStatus.COMPLETED
                            if workstation.verified
                            else GuidanceStatus.BLOCKED
                        ),
                        objective=route.objective,
                        action=workstation.intent.action.value,
                        gestures_sent=workstation.gestures_sent,
                        verified=workstation.verified,
                        message=workstation.message,
                    )
                else:
                    result = asyncio.run(
                        service.operate(
                            route.objective,
                            recommendation=current_recommendation,
                        )
                    )
            else:
                typer.echo(
                    "I could not safely distinguish a question from an action. Rephrase as a "
                    "question, or use `/operate <objective>` to delegate explicitly."
                )
                continue
            typer.echo(render_guidance(result))
        except (
            ComputerControlError,
            GameBridgeError,
            SoftwareIncError,
            OSError,
            ValidationError,
        ) as error:
            typer.echo(f"error[{type(error).__name__}]: {error}", err=True)


@software_inc_probe_app.command("doctor")
def software_inc_probe_doctor() -> None:
    """Report official probe source, ownership, enablement, and load evidence."""
    try:
        report = _software_inc_probe_installer().diagnose()
        _emit(report)
        if not report.discovery.installed:
            raise typer.Exit(SOFTWARE_INC_FAILURE)
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_probe_app.command("install")
def software_inc_probe_install() -> None:
    """Install only the checksum-recorded official source probe."""
    try:
        _emit(_software_inc_probe_installer().install())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_probe_app.command("verify")
def software_inc_probe_verify() -> None:
    """Verify the installed probe and its least-authority source contract."""
    try:
        _emit(_software_inc_probe_installer().verify())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_probe_app.command("disable")
def software_inc_probe_disable() -> None:
    """Disable only the unchanged manifest-owned probe source."""
    try:
        _emit(_software_inc_probe_installer().disable())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_probe_app.command("uninstall")
def software_inc_probe_uninstall() -> None:
    """Remove only unchanged owned probe files and preserve unknown files."""
    try:
        _emit(_software_inc_probe_installer().uninstall())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("doctor")
def software_inc_bridge_doctor() -> None:
    """Report artifact, ownership, broad-access scope, and live-load evidence."""
    try:
        _emit(_software_inc_bridge_installer().diagnose())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("install")
def software_inc_bridge_install(
    approve_broad_access: Annotated[
        bool,
        typer.Option(
            "--approve-broad-access",
            help=(
                "Approve Software Inc. GiveMeFreedom solely for token read and loopback networking."
            ),
        ),
    ] = False,
) -> None:
    """Install the checksum-recorded compiled bridge after explicit authority approval."""
    try:
        _emit(_software_inc_bridge_installer().install(approve_broad_access=approve_broad_access))
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("verify")
def software_inc_bridge_verify() -> None:
    """Verify exact owned bridge bytes, game identity, and private token."""
    try:
        _emit(_software_inc_bridge_installer().verify())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("disable")
def software_inc_bridge_disable() -> None:
    """Disable only the unchanged manifest-owned bridge DLL."""
    try:
        _emit(_software_inc_bridge_installer().disable())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("uninstall")
def software_inc_bridge_uninstall() -> None:
    """Remove only unchanged owned bridge state and preserve unknown files."""
    try:
        _emit(_software_inc_bridge_installer().uninstall())
    except SoftwareIncError as error:
        _fail(error, SOFTWARE_INC_FAILURE)


async def _software_inc_bridge_capabilities_async() -> BaseModel:
    client = software_inc_bridge_client()
    try:
        return await client.connect()
    finally:
        await client.close()


async def _software_inc_bridge_observe_async() -> GameSnapshot:
    client = software_inc_bridge_client()
    try:
        await client.connect()
        return await client.request_full_snapshot()
    finally:
        await client.close()


@software_inc_bridge_app.command("capabilities")
def software_inc_bridge_capabilities() -> None:
    """Authenticate and print the running bridge's empty action catalog."""
    try:
        _emit(asyncio.run(_software_inc_bridge_capabilities_async()))
    except (ComputerControlError, GameBridgeError, SoftwareIncError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("observe")
def software_inc_bridge_observe(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Request one main-thread, authenticated semantic snapshot."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        if json_output:
            _emit(snapshot)
        else:
            coverage = ", ".join(
                f"{item.coverage.surface}={item.coverage.status.value}"
                for item in snapshot.surfaces
            )
            typer.echo(
                f"Software Inc. {snapshot.game_version} bridge snapshot "
                f"{snapshot.bridge_sequence}: {coverage}"
            )
    except (ComputerControlError, GameBridgeError, SoftwareIncError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("list")
def software_inc_bridge_list(
    surface: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List teams, employees, work-items, products, or another observed surface."""
    try:
        observed = software_inc_surface_from(
            asyncio.run(_software_inc_bridge_observe_async()), surface
        )
        if json_output:
            _emit([entity.model_dump(mode="json") for entity in observed.entities])
        else:
            typer.echo(render_software_inc_surface(observed))
    except (ComputerControlError, GameBridgeError, SoftwareIncError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("show")
def software_inc_bridge_show(
    surface: str,
    reference: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one entity by stable ID or an exact observed string value."""
    try:
        entity = software_inc_entity_from(
            asyncio.run(_software_inc_bridge_observe_async()), surface, reference
        )
        _emit(entity) if json_output else typer.echo(render_software_inc_entity(entity))
    except (ComputerControlError, GameBridgeError, SoftwareIncError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_bridge_app.command("prove-read-only")
def software_inc_bridge_prove_read_only() -> None:
    """Prove paused semantics and all discovered save bytes survive reconnect unchanged."""
    try:
        proof = asyncio.run(prove_software_inc_read_only_bridge())
        _emit(proof)
        if not proof.passed:
            raise typer.Exit(SOFTWARE_INC_FAILURE)
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_ui_app.command("doctor")
def software_inc_ui_doctor() -> None:
    """Verify the exact-window, permission, bridge, and current-scene UI gate."""
    try:
        report = asyncio.run(diagnose_software_inc_ui())
        _emit(report)
        if not report.safe:
            raise typer.Exit(SOFTWARE_INC_FAILURE)
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


async def _software_inc_ui_observe_async():
    return (await SoftwareIncUIObserver().observe()).observation


def _approve_software_inc_workstation(plan: WorkstationPlan) -> bool:
    if plan.assign_room_to_team:
        typer.echo(
            f"Approval required: assign room {plan.room_id} to "
            f"{plan.team_name} and commit this exact workstation setup:"
        )
    else:
        typer.echo(
            f"Approval required: room {plan.room_id} is already assigned to "
            f"{plan.team_name}; commit this exact workstation setup:"
        )
    for component in plan.reused_components:
        typer.echo(
            f"  Reuse existing {component.display_name} "
            f"[{component.prefab_name}] ({component.equipment_id})"
        )
    for line in plan.line_items:
        inventory = " (use observed inventory; $0 cash)" if line.expected_cash_charge == 0 else ""
        typer.echo(
            f"  {line.sequence}. 1x {line.catalog_item.display_name} "
            f"[{line.catalog_item.prefab_name}] at ${line.total_price:,.2f}{inventory}"
        )
    typer.echo(
        f"Exact cash charge: ${plan.total_one_time_cost:,.2f}; "
        f"projected cash: ${plan.projected_cash_after:,.2f}; "
        f"minimum reserve: ${plan.minimum_cash_reserve:,.2f}."
    )
    typer.echo(
        "Fixed recurring monthly cost: $0.00. Observed equipment wattage: "
        f"{plan.observed_variable_wattage}; usage-based electricity is not "
        "deterministically projected."
    )
    question = (
        "Approve this exact room assignment and itemized commitment?"
        if plan.assign_room_to_team
        else "Approve this exact itemized commitment in the already-assigned room?"
    )
    return typer.confirm(question, default=False)


async def _execute_software_inc_workstation(
    instruction: str, *, dry_run: bool
) -> WorkstationOperationResult:
    return await execute_workstation_intent(
        parse_workstation_intent(instruction),
        dry_run=dry_run,
        approval_provider=None if dry_run else _approve_software_inc_workstation,
    )


@software_inc_ui_app.command("observe")
def software_inc_ui_observe(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Synchronize read-only semantics with one exact-window screenshot."""
    try:
        observation = asyncio.run(_software_inc_ui_observe_async())
        if json_output:
            _emit(observation)
        else:
            targets = ", ".join(target.target_id for target in observation.targets) or "none"
            typer.echo(
                f"Software Inc. scene={observation.scene.value}; "
                f"paused={str(observation.paused).lower()}; "
                f"modal={observation.modal_state.value}; targets={targets}; "
                f"frame={observation.frame.frame_id[:12]}; "
                f"bridge_sequence={observation.semantic_after.bridge_sequence}"
            )
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_ui_app.command("capabilities")
def software_inc_ui_capabilities() -> None:
    """Print the separate visible-UI catalog while semantic actions remain empty."""
    try:
        catalog = asyncio.run(SoftwareIncUIObserver().capabilities())
        _emit(catalog)
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_ui_app.command("do")
def software_inc_ui_do(
    instruction: str,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute one bounded plain-English UI objective and verify every gesture."""
    try:
        try:
            action = parse_software_inc_ui_action(instruction)
        except SoftwareIncUIValidationError:
            if "workstation" in instruction.strip().casefold():
                workstation_result = asyncio.run(
                    _execute_software_inc_workstation(instruction, dry_run=dry_run)
                )
                if json_output:
                    _emit(workstation_result)
                else:
                    typer.echo(workstation_result.message)
                    typer.echo(
                        f"cycles={workstation_result.cycles}; "
                        f"gestures={workstation_result.gestures_sent}; "
                        f"verified={str(workstation_result.verified).lower()}"
                    )
                return
            office_prefix = (
                instruction.strip().casefold().startswith(("assign ", "configure ", "set "))
            )
            if office_prefix:
                office_intent = parse_office_intent(instruction)
                office_result = asyncio.run(execute_office_intent(office_intent, dry_run=dry_run))
                if json_output:
                    _emit(office_result)
                else:
                    typer.echo(office_result.message)
                    typer.echo(
                        f"cycles={office_result.cycles}; "
                        f"gestures={office_result.gestures_sent}; "
                        f"verified={str(office_result.verified).lower()}"
                    )
                return
            staffing_intent = parse_staffing_intent(instruction)

            def approve_staffing(plan: StaffingPlan, _: StaffingApproval) -> bool:
                if plan.action.value == "observe_applicants":
                    typer.echo(
                        f"Approval required: spend ${plan.expected_one_time_cost:,.2f} once "
                        f"to search for Programmer applicants for {plan.team_name}."
                    )
                elif plan.action.value == "hire_employee":
                    assert plan.applicant is not None
                    typer.echo(
                        f"Approval required: hire {plan.applicant.name} "
                        f"({plan.applicant.applicant_id}) into {plan.team_name} for "
                        f"${plan.expected_monthly_cost:,.2f}/month; "
                        f"cap=${plan.maximum_monthly_salary:,.2f}."
                    )
                else:
                    typer.echo(f"Approval required: create team {plan.team_name!r}.")
                return typer.confirm("Approve this exact in-game commitment?", default=False)

            staffing_result = asyncio.run(
                execute_staffing_intent(
                    staffing_intent,
                    dry_run=dry_run,
                    approval_provider=None if dry_run else approve_staffing,
                )
            )
            if json_output:
                _emit(staffing_result)
            else:
                typer.echo(staffing_result.message)
                typer.echo(
                    f"cycles={staffing_result.cycles}; "
                    f"gestures={staffing_result.gestures_sent}; "
                    f"verified={str(staffing_result.verified).lower()}"
                )
            return
        result = asyncio.run(execute_software_inc_ui_action(action, dry_run=dry_run))
        if json_output:
            _emit(result)
        else:
            typer.echo(result.message)
            typer.echo(
                f"cycles={result.cycles}; gestures={result.gestures_sent}; "
                f"verified={str(result.verified).lower()}"
            )
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_office_app.command("readiness")
def software_inc_office_readiness(
    team: Annotated[str, typer.Argument(help="Exact observed team name.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain observed workspace, room, cost, and server readiness without input."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        readiness = project_team_readiness(snapshot, team)
        if json_output:
            _emit(readiness)
            return
        typer.echo(
            f"{readiness.team_name}: capacity {readiness.current_capacity}/"
            f"{readiness.required_capacity}; working hours "
            f"{readiness.work_start}-{readiness.work_end}."
        )
        if readiness.exact_missing_resource is None:
            typer.echo("Workspace: sufficient observed valid workstation capacity.")
        else:
            typer.echo(f"Missing: {readiness.exact_missing_resource}.")
        if readiness.cheaper_existing_capacity:
            typer.echo(
                "Cheaper existing assignment candidates: "
                + ", ".join(readiness.cheaper_existing_capacity)
            )
        if readiness.one_time_cost is not None:
            typer.echo(
                f"Exact one-time cash requirement: ${readiness.one_time_cost:,.2f}; "
                f"projected cash: ${readiness.cash_reserve_after_purchase:,.2f}."
                if readiness.cash_reserve_after_purchase is not None
                else f"Exact one-time cash requirement: ${readiness.one_time_cost:,.2f}."
            )
        if readiness.recurring_cost is not None:
            typer.echo(f"Fixed recurring monthly cost: ${readiness.recurring_cost:,.2f}.")
        typer.echo(
            "Servers: observed="
            f"{len(readiness.servers)}; universal source-control prerequisite=false."
        )
        if readiness.material_unknowns:
            typer.echo("Unknowns: " + " ".join(readiness.material_unknowns))
    except (ComputerControlError, GameBridgeError, SoftwareIncError, OSError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


async def _software_inc_contract_snapshot(*, dry_run: bool = False) -> GameSnapshot:
    result = await browse_contracts(dry_run=dry_run)
    if dry_run and not result.verified:
        raise SoftwareIncUIValidationError(result.message)
    return await _software_inc_bridge_observe_async()


def _contract_approval(approval: ContractApproval) -> bool:
    typer.echo("Approval required: " + approval.action_summary)
    return typer.confirm("Approve this exact in-game commitment?", default=False)


def _render_contract_recommendation(recommendation: ContractRecommendation) -> None:
    candidate = recommendation.recommended
    if candidate is None:
        typer.echo(
            f"No eligible contract; {recommendation.rejected_count} observed candidates "
            "were rejected."
        )
        for reason in recommendation.rejection_reasons:
            typer.echo("Rejected because: " + reason)
        for unknown in recommendation.material_unknowns:
            typer.echo("Unknown: " + unknown)
        return
    contract = candidate.contract
    team = candidate.team
    typer.echo(
        f"Recommend: {contract.name} from {contract.client} — ${contract.reward:,.2f} reward, "
        f"${contract.penalty:,.2f} maximum penalty, deadline {contract.deadline}."
    )
    typer.echo(
        f"Team {team.team_name}: roles {', '.join(team.observed_roles) or 'none'}; "
        f"workspace {team.current_workspace_capacity}/{team.required_workspace_capacity}; "
        f"conservative deadline buffer {team.deadline_buffer_days} days."
    )
    typer.echo(
        f"Worst-case cash after full penalty: ${candidate.worst_case_cash_after_penalty:,.2f}."
    )
    for alternative in recommendation.alternatives:
        typer.echo(
            f"Alternative: {alternative.contract.name} from {alternative.contract.client} — "
            f"${alternative.contract.reward:,.2f}."
        )


def _render_contract_operation(result: object, *, json_output: bool) -> None:
    if json_output:
        _emit(result)
        return
    message = getattr(result, "message", None)
    if not isinstance(message, str):
        raise SoftwareIncUIValidationError("contract operation returned no status message")
    typer.echo(message)


@software_inc_contracts_app.command("browse")
def software_inc_contracts_browse(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Open the visible Contracts window and prove complete market observation."""
    try:
        result = asyncio.run(browse_contracts(dry_run=dry_run))
        if json_output:
            _emit(result)
        else:
            typer.echo(result.message)
            typer.echo(f"gestures={result.gestures_sent}; verified={str(result.verified).lower()}")
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("list")
def software_inc_contracts_list(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List exact available contracts after visible browsing."""
    try:
        snapshot = asyncio.run(_software_inc_contract_snapshot())
        contracts = available_contracts(snapshot)
        if json_output:
            _emit(contracts)
            return
        if not contracts:
            typer.echo("No available contracts are currently visible.")
            return
        for contract in contracts:
            typer.echo(
                f"[{contract.display_index}] {contract.name} — {contract.client}; "
                f"reward=${contract.reward:,.2f}; penalty=${contract.penalty:,.2f}; "
                f"completion_window={contract.deadline}"
            )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("recommend")
def software_inc_contracts_recommend(
    team: Annotated[str, typer.Option("--team", help="Exact observed team name.")],
    minimum_reward: Annotated[
        float, typer.Option("--minimum-reward", min=0, help="Minimum acceptable USD reward.")
    ],
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 0.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Recommend at most one contract plus two observed alternatives."""
    try:
        snapshot = asyncio.run(_software_inc_contract_snapshot())
        recommendation = recommend_contracts(
            snapshot,
            team_name=team,
            minimum_reward=Decimal(str(minimum_reward)),
            minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
        )
        _emit(recommendation) if json_output else _render_contract_recommendation(recommendation)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("accept")
def software_inc_contracts_accept(
    team: Annotated[str, typer.Option("--team", help="Exact observed team name.")],
    minimum_reward: Annotated[float, typer.Option("--minimum-reward", min=0)],
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 0.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Recommend, explicitly approve, accept, assign, and verify one contract."""
    try:
        snapshot = asyncio.run(_software_inc_contract_snapshot(dry_run=dry_run))
        recommendation = recommend_contracts(
            snapshot,
            team_name=team,
            minimum_reward=Decimal(str(minimum_reward)),
            minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
        )
        result = asyncio.run(
            accept_recommended_contract(
                recommendation,
                approval_provider=None if dry_run else _contract_approval,
                dry_run=dry_run,
            )
        )
        if json_output:
            _emit(result)
        else:
            typer.echo(result.message)
            typer.echo(f"gestures={result.gestures_sent}; verified={str(result.verified).lower()}")
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _current_contract_workflow(snapshot: GameSnapshot):
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    workflow = ContractWorkflowStore().current(
        game_session_id=snapshot.game_session_id, save_identity=save_identity
    )
    if workflow is None:
        raise SoftwareIncUIValidationError("no active contract workflow exists for this save")
    return workflow


@software_inc_contracts_app.command("status")
def software_inc_contracts_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the persisted workflow and current semantic work-item state."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
        repository = ContractWorkflowStore()
        workflow = repository.current(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        ) or repository.latest(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        )
        if workflow is None:
            raise SoftwareIncUIValidationError("no contract workflow exists for the current save")
        work = [
            item
            for item in active_contract_work(snapshot)
            if item.contract_id == workflow.contract_id
            or (item.contract_name == workflow.contract_name and item.client == workflow.client)
        ]
        if json_output:
            _emit({"workflow": workflow, "work_items": work})
            return
        typer.echo(
            f"{workflow.contract_name}: workflow={workflow.status.value}; "
            f"observed_stage={workflow.observed_stage.value}; team={workflow.team_name}."
        )
        for item in work:
            deadline = "not started" if item.contract_started is False else str(item.days_remaining)
            typer.echo(
                f"work_item={item.work_item_id}; stage={item.stage.value}; "
                f"progress={item.progress}; bugs={item.bugs}; fixed_bugs={item.fixed_bugs}; "
                f"days_remaining={deadline}."
            )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("advance")
def software_inc_contracts_advance(
    seconds: Annotated[float, typer.Option("--seconds", min=0.1, max=30)] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run one bounded work interval, then pause and verify progress and bugs."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        workflow = _current_contract_workflow(snapshot)
        result = asyncio.run(
            advance_contract(
                workflow,
                run_seconds=seconds,
                deadline_risk_approval_provider=None if dry_run else _contract_approval,
                dry_run=dry_run,
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("promote")
def software_inc_contracts_promote(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Promote the exact contract only after observed readiness and approval."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        result = asyncio.run(
            promote_contract(
                _current_contract_workflow(snapshot),
                approval_provider=None if dry_run else _contract_approval,
                dry_run=dry_run,
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("review")
def software_inc_contracts_review(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Open, approve, start, and verify one exact safe contract review."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        result = asyncio.run(
            review_contract(
                _current_contract_workflow(snapshot),
                approval_provider=None if dry_run else _contract_approval,
                dry_run=dry_run,
            )
        )
        _render_contract_operation(result, json_output=json_output)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("release")
def software_inc_contracts_release(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Release the exact contract only when the live UI exposes its valid action."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        result = asyncio.run(
            release_contract(
                _current_contract_workflow(snapshot),
                approval_provider=None if dry_run else _contract_approval,
                dry_run=dry_run,
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_contracts_app.command("do")
def software_inc_contracts_do(
    instruction: Annotated[str, typer.Argument(help="One bounded plain-English contract action.")],
    seconds: Annotated[
        float,
        typer.Option("--seconds", min=0.1, max=30, help="Bounded real-time work interval."),
    ] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute one deterministic Prompt 6A request from plain English."""
    try:
        intent = parse_contract_intent(instruction)
        if intent.action is ContractIntentAction.BROWSE:
            result = asyncio.run(browse_contracts(dry_run=dry_run))
            _render_contract_operation(result, json_output=json_output)
            return
        if intent.action in {ContractIntentAction.RECOMMEND, ContractIntentAction.ACCEPT}:
            if intent.team_name is None or intent.minimum_reward is None:
                raise SoftwareIncUIValidationError(
                    "contract recommendation requires an exact team and reward floor"
                )
            snapshot = asyncio.run(_software_inc_contract_snapshot(dry_run=dry_run))
            recommendation = recommend_contracts(
                snapshot,
                team_name=intent.team_name,
                minimum_reward=intent.minimum_reward,
                minimum_cash_reserve=intent.minimum_cash_reserve,
            )
            if intent.action is ContractIntentAction.RECOMMEND:
                _emit(recommendation) if json_output else _render_contract_recommendation(
                    recommendation
                )
                return
            result = asyncio.run(
                accept_recommended_contract(
                    recommendation,
                    approval_provider=None if dry_run else _contract_approval,
                    dry_run=dry_run,
                )
            )
            _render_contract_operation(result, json_output=json_output)
            return

        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        workflow = _current_contract_workflow(snapshot)
        if intent.action is ContractIntentAction.ADVANCE:
            result = asyncio.run(
                advance_contract(
                    workflow,
                    run_seconds=seconds,
                    deadline_risk_approval_provider=None if dry_run else _contract_approval,
                    dry_run=dry_run,
                )
            )
        elif intent.action is ContractIntentAction.REVIEW:
            result = asyncio.run(
                review_contract(
                    workflow,
                    approval_provider=None if dry_run else _contract_approval,
                    dry_run=dry_run,
                )
            )
        elif intent.action is ContractIntentAction.PROMOTE:
            result = asyncio.run(
                promote_contract(
                    workflow,
                    approval_provider=None if dry_run else _contract_approval,
                    dry_run=dry_run,
                )
            )
        elif intent.action is ContractIntentAction.RELEASE:
            result = asyncio.run(
                release_contract(
                    workflow,
                    approval_provider=None if dry_run else _contract_approval,
                    dry_run=dry_run,
                )
            )
        else:  # pragma: no cover - exhaustive enum guard
            raise SoftwareIncUIValidationError(
                f"unsupported contract action {intent.action.value!r}"
            )
        _render_contract_operation(result, json_output=json_output)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _training_approval(approval: TrainingApproval) -> bool:
    typer.echo("Approval required: " + approval.action_summary)
    return typer.confirm("Approve this exact education commitment?", default=False)


def _render_training_recommendation(recommendation: TrainingRecommendation) -> None:
    candidate = recommendation.recommended
    if candidate is None:
        typer.echo(
            f"No eligible education candidate; {recommendation.rejected_count} observed "
            "employees were rejected."
        )
        for reason in recommendation.rejection_reasons:
            typer.echo("Rejected because: " + reason)
        return
    employee = candidate.employee
    typer.echo(
        f"Recommend: {employee.employee_name} from {employee.team_name} — "
        f"Designer/System level {employee.level} -> {candidate.target_level}, "
        f"three sequential one-month courses, projected direct cost "
        f"${candidate.projected_direct_cost:,.2f}."
    )
    typer.echo(
        f"Team capacity {candidate.team_capacity_before} -> "
        f"{candidate.team_capacity_during}; continuing payroll during education "
        f"${candidate.payroll_during_training:,.2f}; cash after projected direct cost "
        f"${candidate.cash_after_projected_cost:,.2f}. First course: "
        f"${candidate.current_course_cost:,.2f}."
    )
    for alternative in recommendation.alternatives:
        typer.echo(
            f"Alternative: {alternative.employee.employee_name}; Designer/System level "
            f"{alternative.employee.level}; projected cost "
            f"${alternative.projected_direct_cost:,.2f}."
        )
    for unknown in recommendation.material_unknowns:
        typer.echo("Unknown: " + unknown)


def _current_training_workflow(snapshot: GameSnapshot) -> TrainingWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    workflow = TrainingWorkflowStore().current(
        game_session_id=snapshot.game_session_id, save_identity=save_identity
    )
    if workflow is None:
        raise SoftwareIncUIValidationError("no active education workflow exists for this save")
    return workflow


@software_inc_training_app.command("recommend")
def software_inc_training_recommend(
    team: Annotated[str, typer.Option("--team", help="Exact observed team name.")] = "Core",
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 0.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Recommend one employee for three sequential Designer/System courses."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        recommendation = recommend_training(
            snapshot,
            team_name=team,
            minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
        )
        _emit(recommendation) if json_output else _render_training_recommendation(recommendation)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_training_app.command("start")
def software_inc_training_start(
    team: Annotated[str, typer.Option("--team", help="Exact observed team name.")] = "Core",
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 0.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Approve and start the next exact one-month course in a three-course curriculum."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
        existing = TrainingWorkflowStore().current(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        )
        recommendation = (
            None
            if existing is not None
            else recommend_training(
                snapshot,
                team_name=team,
                minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
            )
        )
        result = asyncio.run(
            start_training(
                recommendation,
                approval_provider=None if dry_run else _training_approval,
                dry_run=dry_run,
                existing_workflow=existing,
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_training_app.command("status")
def software_inc_training_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show persisted and current semantic education state."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
        repository = TrainingWorkflowStore()
        workflow = repository.current(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        ) or repository.latest(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        )
        if workflow is None:
            raise SoftwareIncUIValidationError("no education workflow exists for this save")
        observed = exact_employee_training(
            snapshot,
            employee_id=workflow.employee_id,
            role="Designer",
            specialization="System",
        )
        if json_output:
            _emit({"workflow": workflow, "observed": observed})
        else:
            typer.echo(
                f"{workflow.employee_name}: workflow={workflow.status.value}; "
                f"Designer/System={observed.level}; active_courses="
                f"{', '.join(observed.active_courses) or 'none'}."
            )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_training_app.command("advance")
def software_inc_training_advance(
    seconds: Annotated[float, typer.Option("--seconds", min=0.1, max=30)] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run one bounded interval, guarantee pause, and verify education progress."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        result = asyncio.run(
            advance_training(
                _current_training_workflow(snapshot),
                run_seconds=seconds,
                dry_run=dry_run,
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_training_app.command("do")
def software_inc_training_do(
    instruction: Annotated[str, typer.Argument(help="One bounded plain-English education action.")],
    seconds: Annotated[float, typer.Option("--seconds", min=0.1, max=30)] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute one deterministic Prompt 6B request from plain English."""
    try:
        intent = parse_training_intent(instruction)
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        if intent.action in {TrainingIntentAction.RECOMMEND, TrainingIntentAction.START}:
            if intent.team_name is None or intent.minimum_cash_reserve is None:
                raise SoftwareIncUIValidationError(
                    "education recommendation requires exact team and cash reserve"
                )
            if intent.action is TrainingIntentAction.RECOMMEND:
                recommendation = recommend_training(
                    snapshot,
                    team_name=intent.team_name,
                    minimum_cash_reserve=intent.minimum_cash_reserve,
                )
                _emit(recommendation) if json_output else _render_training_recommendation(
                    recommendation
                )
                return
            save_identity = json.dumps(
                snapshot.save_identity.model_dump(mode="json"), sort_keys=True
            )
            existing = TrainingWorkflowStore().current(
                game_session_id=snapshot.game_session_id, save_identity=save_identity
            )
            recommendation = (
                None
                if existing is not None
                else recommend_training(
                    snapshot,
                    team_name=intent.team_name,
                    minimum_cash_reserve=intent.minimum_cash_reserve,
                )
            )
            result = asyncio.run(
                start_training(
                    recommendation,
                    approval_provider=None if dry_run else _training_approval,
                    dry_run=dry_run,
                    existing_workflow=existing,
                )
            )
        elif intent.action is TrainingIntentAction.ADVANCE:
            result = asyncio.run(
                advance_training(
                    _current_training_workflow(snapshot),
                    run_seconds=seconds,
                    dry_run=dry_run,
                )
            )
        else:
            workflow = _current_training_workflow(snapshot)
            observed = exact_employee_training(
                snapshot,
                employee_id=workflow.employee_id,
                role="Designer",
                specialization="System",
            )
            _emit({"workflow": workflow, "observed": observed}) if json_output else typer.echo(
                f"{workflow.employee_name}: {workflow.status.value}; System level "
                f"{observed.level}; courses={', '.join(observed.active_courses) or 'none'}."
            )
            return
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _product_approval(approval: ProductApproval) -> bool:
    typer.echo("Approval required: " + approval.action_summary)
    return typer.confirm("Approve this exact Atlas commitment?", default=False)


def _product_approval_provider(auto_approve: bool) -> Callable[[ProductApproval], bool]:
    return (lambda _approval: True) if auto_approve else _product_approval


def _render_product_recommendation(recommendation: ProductRecommendation) -> None:
    configuration = recommendation.configuration
    runway = recommendation.runway
    typer.echo(
        f"{'Recommend' if recommendation.recommended else 'Reject'}: "
        f"{configuration.name} — {configuration.product_type}/{configuration.category}; "
        f"features {', '.join(configuration.features)}; OS "
        f"{', '.join(configuration.operating_systems)}; team "
        f"{recommendation.team.team_name}; price ${configuration.price:,.2f}."
    )
    typer.echo(
        f"Conservative runway: cash ${runway.observed_cash:,.2f}; "
        f"{runway.conservative_months:g} month(s); payroll "
        f"${runway.observed_monthly_payroll:,.2f}/month; infrastructure "
        f"${runway.observed_monthly_infrastructure:,.2f}/month; projected "
        f"${runway.projected_cash_after:,.2f}; reserve "
        f"${runway.minimum_cash_reserve:,.2f}."
    )
    for reason in recommendation.reasons:
        typer.echo("Rejected because: " + reason)
    for unknown in recommendation.material_unknowns:
        typer.echo("Unknown: " + unknown)


def _current_product_workflow(
    snapshot: GameSnapshot, *, include_completed: bool = False
) -> ProductWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    repository = ProductWorkflowStore()
    workflow = repository.current(
        game_session_id=snapshot.game_session_id, save_identity=save_identity
    )
    if workflow is None and include_completed:
        workflow = repository.latest(
            game_session_id=snapshot.game_session_id, save_identity=save_identity
        )
    if workflow is None:
        raise SoftwareIncUIValidationError("no Atlas workflow exists for this save")
    return workflow


@software_inc_products_app.command("types")
def software_inc_products_types(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List the version-pinned Atlas 2D Editor type observation."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        observed = product_type(snapshot, ATLAS_PRODUCT_TYPE)
        _emit(observed) if json_output else typer.echo(
            f"{observed.name}: unlocked={observed.unlocked}; categories="
            f"{', '.join(observed.categories)}; optimal development time "
            f"{observed.optimal_development_time:g}."
        )
    except (GameBridgeError, SoftwareIncError, OSError, ValidationError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("features")
def software_inc_products_features(
    product_type_name: Annotated[str, typer.Option("--type")] = ATLAS_PRODUCT_TYPE,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List exact current product features and declared dependencies."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        features = product_features(snapshot, product_type_name)
        if json_output:
            _emit(features)
        else:
            for feature in features:
                typer.echo(
                    f"{feature.name}: specialization={feature.specialization or 'none'}; "
                    f"dependencies={', '.join(feature.dependencies) or 'none'}; "
                    f"dev_time={feature.development_time:g}; "
                    f"server={feature.server_requirement:g}; unlocked={feature.unlocked}."
                )
    except (GameBridgeError, SoftwareIncError, OSError, ValidationError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("operating-systems")
def software_inc_products_operating_systems(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show available and selected OSes from the visible design window."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        values = product_ui_state(snapshot).values
        if values.get("scene") != "product_configuration":
            raise SoftwareIncUIValidationError(
                "open the New software design window to observe current operating systems"
            )
        options = operating_system_options(snapshot)
        result = {
            "available": options,
            "selected": values.get("selected_operating_systems", ""),
        }
        if json_output:
            _emit(result)
        else:
            for option in options:
                typer.echo(
                    f"{option.product_id}:{option.name}: userbase={option.userbase:,}; "
                    f"release={option.release_date}; selected={option.selected}."
                )
            typer.echo("Selected: " + (str(result["selected"]).replace("|", ", ") or "none"))
    except (GameBridgeError, SoftwareIncError, OSError, ValidationError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("recommend")
def software_inc_products_recommend(
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 50000.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Recommend the exact currently visible Atlas configuration without input."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        recommendation = recommend_atlas(
            snapshot,
            minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
        )
        _emit(recommendation) if json_output else _render_product_recommendation(recommendation)
    except (GameBridgeError, SoftwareIncError, OSError, ValidationError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("start")
def software_inc_products_start(
    minimum_cash_reserve: Annotated[float, typer.Option("--minimum-cash-reserve", min=0)] = 50000.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Preauthorize the exact fresh Atlas commitment (sandbox)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Configure, approve, and create the exact Atlas design."""
    try:
        result = asyncio.run(
            start_atlas(
                minimum_cash_reserve=Decimal(str(minimum_cash_reserve)),
                approval_provider=None if dry_run else _product_approval_provider(yes),
                dry_run=dry_run,
                progress_provider=(
                    None if json_output else lambda message: typer.echo("Atlas: " + message)
                ),
            )
        )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("close")
def software_inc_products_close(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Close the reversible product configuration window."""
    try:
        result = asyncio.run(close_product_configuration(dry_run=dry_run))
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("status")
def software_inc_products_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show persisted Atlas state beside the current semantic work item."""
    try:
        snapshot = asyncio.run(_software_inc_bridge_observe_async())
        workflow = _current_product_workflow(snapshot, include_completed=True)
        observed = product_work(snapshot, workflow.product_name)
        if json_output:
            _emit({"workflow": workflow, "observed": observed})
        else:
            typer.echo(
                f"Atlas: workflow={workflow.status.value}; stage={workflow.stage.value}; "
                f"progress={workflow.progress:g}; iteration={workflow.iteration}; "
                f"held={workflow.held}; game_paused="
                f"{snapshot.game_state.get('simulation_speed') in {'0', '0.0'}}."
            )
    except (GameBridgeError, SoftwareIncError, OSError, ValidationError) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _run_product_action(
    action: ProductIntentAction,
    snapshot: GameSnapshot,
    *,
    seconds: float,
    dry_run: bool,
    auto_approve: bool = False,
) -> ProductOperationResult:
    workflow = _current_product_workflow(
        snapshot,
        include_completed=action in {ProductIntentAction.ADVANCE, ProductIntentAction.PROMOTE},
    )
    if action is ProductIntentAction.ADVANCE:
        return asyncio.run(advance_product(workflow, run_seconds=seconds, dry_run=dry_run))
    if action is ProductIntentAction.REVIEW:
        return asyncio.run(
            review_product(
                workflow,
                approval_provider=(None if dry_run else _product_approval_provider(auto_approve)),
                dry_run=dry_run,
            )
        )
    if action is ProductIntentAction.ITERATE:
        return asyncio.run(
            iterate_product(
                workflow,
                approval_provider=(None if dry_run else _product_approval_provider(auto_approve)),
                dry_run=dry_run,
            )
        )
    if action is ProductIntentAction.PROMOTE:
        return asyncio.run(
            promote_product(
                workflow,
                approval_provider=(None if dry_run else _product_approval_provider(auto_approve)),
                dry_run=dry_run,
            )
        )
    if action in {ProductIntentAction.HOLD, ProductIntentAction.RESUME}:
        return asyncio.run(
            set_product_hold(
                workflow,
                held=action is ProductIntentAction.HOLD,
                dry_run=dry_run,
            )
        )
    raise SoftwareIncUIValidationError(f"unsupported Atlas action {action.value!r}")


def _product_action_command(
    action: ProductIntentAction,
    *,
    seconds: float = 10.0,
    dry_run: bool,
    json_output: bool,
    auto_approve: bool = False,
) -> None:
    snapshot = asyncio.run(_software_inc_bridge_observe_async())
    result = _run_product_action(
        action,
        snapshot,
        seconds=seconds,
        dry_run=dry_run,
        auto_approve=auto_approve,
    )
    _emit(result) if json_output else typer.echo(result.message)


@software_inc_products_app.command("advance")
def software_inc_products_advance(
    seconds: Annotated[float, typer.Option("--seconds", min=0.1, max=30)] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run one bounded Atlas interval and guarantee pause."""
    try:
        _product_action_command(
            ProductIntentAction.ADVANCE,
            seconds=seconds,
            dry_run=dry_run,
            json_output=json_output,
        )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _simple_product_command(
    action: ProductIntentAction,
    *,
    dry_run: bool,
    json_output: bool,
    auto_approve: bool = False,
) -> None:
    _product_action_command(
        action,
        dry_run=dry_run,
        json_output=json_output,
        auto_approve=auto_approve,
    )


@software_inc_products_app.command("review")
def software_inc_products_review(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Preauthorize the exact fresh review commitment (sandbox)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Configure and approve an exact Atlas review."""
    try:
        _simple_product_command(
            ProductIntentAction.REVIEW,
            dry_run=dry_run,
            json_output=json_output,
            auto_approve=yes,
        )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("iterate")
def software_inc_products_iterate(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Preauthorize the exact fresh iteration commitment (sandbox)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Approve iteration from the exact Atlas review result."""
    try:
        _simple_product_command(
            ProductIntentAction.ITERATE,
            dry_run=dry_run,
            json_output=json_output,
            auto_approve=yes,
        )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("promote")
def software_inc_products_promote(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Preauthorize the exact fresh stage commitment (sandbox)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Approve the next exact Atlas stage transition."""
    try:
        _simple_product_command(
            ProductIntentAction.PROMOTE,
            dry_run=dry_run,
            json_output=json_output,
            auto_approve=yes,
        )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("hold")
def software_inc_products_hold(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Hold Atlas without advancing game time."""
    try:
        _simple_product_command(ProductIntentAction.HOLD, dry_run=dry_run, json_output=json_output)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("resume")
def software_inc_products_resume(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Resume Atlas project work without advancing game time."""
    try:
        _simple_product_command(
            ProductIntentAction.RESUME, dry_run=dry_run, json_output=json_output
        )
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


@software_inc_products_app.command("do")
def software_inc_products_do(
    instruction: Annotated[str, typer.Argument(help="One bounded plain-English Atlas action.")],
    seconds: Annotated[float, typer.Option("--seconds", min=0.1, max=30)] = 10.0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Preauthorize an exact fresh Atlas commitment (sandbox)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute one deterministic Prompt 7 request from plain English."""
    try:
        intent = parse_product_intent(instruction)
        if intent.mapping_note and not json_output:
            typer.echo("Version mapping: " + intent.mapping_note)
        if intent.action is ProductIntentAction.CREATE:
            result = asyncio.run(
                start_atlas(
                    minimum_cash_reserve=intent.minimum_cash_reserve,
                    approval_provider=None if dry_run else _product_approval_provider(yes),
                    dry_run=dry_run,
                    progress_provider=(
                        None if json_output else lambda message: typer.echo("Atlas: " + message)
                    ),
                )
            )
        else:
            snapshot = asyncio.run(_software_inc_bridge_observe_async())
            if intent.action is ProductIntentAction.STATUS:
                workflow = _current_product_workflow(snapshot, include_completed=True)
                _emit(
                    {"workflow": workflow, "observed": product_work(snapshot, "Atlas")}
                ) if json_output else typer.echo(
                    f"Atlas is {workflow.stage.value}; progress {workflow.progress:g}; "
                    f"held={workflow.held}."
                )
                return
            result = _run_product_action(
                intent.action,
                snapshot,
                seconds=seconds,
                dry_run=dry_run,
                auto_approve=yes,
            )
        _emit(result) if json_output else typer.echo(result.message)
    except (
        ComputerControlError,
        GameBridgeError,
        SoftwareIncError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error, SOFTWARE_INC_FAILURE)


def _rail_route_bridge_installer() -> RailRouteBridgeInstaller:
    return RailRouteBridgeInstaller()


@rail_route_bridge_app.command("doctor")
def rail_route_bridge_doctor() -> None:
    """Diagnose the exact game, loader, architecture, and plugin build prerequisites."""
    try:
        _emit(_rail_route_bridge_installer().diagnose())
    except RailRouteBridgeError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("install")
def rail_route_bridge_install() -> None:
    """Install only pinned, checksummed bridge files and record their ownership."""
    try:
        _emit(_rail_route_bridge_installer().install())
    except RailRouteBridgeError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("verify")
def rail_route_bridge_verify() -> None:
    """Verify installed bridge files and compatibility without launching the game."""
    try:
        _emit(_rail_route_bridge_installer().verify())
    except RailRouteBridgeError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("disable")
def rail_route_bridge_disable() -> None:
    """Disable only the manifest-owned bridge plugin."""
    try:
        _emit(_rail_route_bridge_installer().disable())
    except RailRouteBridgeError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("uninstall")
def rail_route_bridge_uninstall() -> None:
    """Remove unchanged manifest-owned files and preserve everything unrecognized."""
    try:
        _emit(_rail_route_bridge_installer().uninstall())
    except RailRouteBridgeError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


async def _rail_route_bridge_capabilities_async() -> BaseModel:
    client = rail_route_bridge_client()
    try:
        return await client.connect()
    finally:
        await client.close()


async def _rail_route_bridge_observe_async() -> GameSnapshot:
    client = rail_route_bridge_client()
    try:
        await client.connect()
        return await client.request_full_snapshot()
    finally:
        await client.close()


@rail_route_bridge_app.command("capabilities")
def rail_route_bridge_capabilities() -> None:
    """Authenticate and print the running bridge's read-only capability manifest."""
    try:
        _emit(asyncio.run(_rail_route_bridge_capabilities_async()))
    except (GameBridgeError, RailRouteBridgeError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("observe")
def rail_route_bridge_observe(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the complete typed snapshot.")
    ] = False,
) -> None:
    """Request one authenticated full read-only semantic snapshot."""
    try:
        snapshot = asyncio.run(_rail_route_bridge_observe_async())
        if json_output:
            _emit(snapshot)
        else:
            coverage = ", ".join(
                f"{surface.coverage.surface}={surface.coverage.status.value}"
                for surface in snapshot.surfaces
            )
            typer.echo(
                f"Rail Route {snapshot.game_version} bridge snapshot "
                f"{snapshot.bridge_sequence}: {coverage}"
            )
    except (GameBridgeError, RailRouteBridgeError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("list")
def rail_route_bridge_list(
    surface: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List one observed semantic collection, such as trains or stations."""
    try:
        snapshot = asyncio.run(_rail_route_bridge_observe_async())
        observed = surface_from(snapshot, surface)
        if json_output:
            _emit([entity.model_dump(mode="json") for entity in observed.entities])
        else:
            typer.echo(render_rail_route_surface(observed))
    except (GameBridgeError, RailRouteBridgeError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("show")
def rail_route_bridge_show(
    surface: str,
    reference: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one semantic entity by stable ID or exact public name."""
    try:
        snapshot = asyncio.run(_rail_route_bridge_observe_async())
        entity = entity_from(snapshot, surface, reference)
        _emit(entity) if json_output else typer.echo(render_rail_route_entity(entity))
    except (GameBridgeError, RailRouteBridgeError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_bridge_app.command("prove-read-only")
def rail_route_bridge_prove_read_only() -> None:
    """Prove paused semantic and save bytes remain unchanged across observations."""
    try:
        proof = asyncio.run(prove_read_only_bridge())
        _emit(proof)
        if not proof.passed:
            raise typer.Exit(RAIL_ROUTE_FAILURE)
    except (GameBridgeError, RailRouteBridgeError, OSError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_ui_app.command("doctor")
def rail_route_ui_doctor() -> None:
    """Verify the synchronized screenshot, semantic state, and UI action gate."""
    try:
        _emit(asyncio.run(RailRouteUIObserver().capabilities()))
    except (GameBridgeError, RailRouteError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_ui_app.command("observe")
def rail_route_ui_observe() -> None:
    """Capture one synchronized read-only Rail Route UI observation."""
    try:
        observed = asyncio.run(RailRouteUIObserver().observe())
        _emit(observed.observation)
    except (GameBridgeError, RailRouteError) as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_app.command("doctor")
def rail_route_doctor() -> None:
    """Inspect the installed game, running process, version, and permissions."""
    try:
        _emit(RailRouteDiscovery().inspect())
    except RailRouteError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_app.command("status")
def rail_route_status(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the typed observation.")
    ] = False,
) -> None:
    """Observe the live game without sending input."""
    try:
        observation = _rail_route_controller().observe()
        _emit(observation) if json_output else typer.echo(
            f"Rail Route {observation.installation.version}: {observation.screen_state.value}"
        )
    except RailRouteError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_app.command("do")
def rail_route_do(
    instruction: Annotated[str, typer.Argument(help="Plain-English Rail Route instruction.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the typed control result.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate the next UI objective without input.")
    ] = False,
) -> None:
    """Validate, execute at most one input, then verify the effect."""
    try:
        intent = parse_control_intent(instruction)
        if dry_run and intent.action is not RailRouteAction.SET_ROUTE:
            raise RailRouteError("--dry-run is available only for UI route setting")
        if intent.action is RailRouteAction.SET_ROUTE:
            result = asyncio.run(execute_set_route_ui(intent, dry_run=dry_run))
            append_ui_trace(result)
        else:
            result = _rail_route_controller().execute(intent)
        _emit(result) if json_output else typer.echo(result.message)
    except RailRouteError as error:
        _fail(error, RAIL_ROUTE_FAILURE)


@rail_route_app.command("play")
def rail_route_play() -> None:
    """Run an interactive, capability-gated Rail Route control session."""
    controller = _rail_route_controller()
    typer.echo("Sim Pilot Rail Route — verified actions: status, pause, resume, set_route_ui")
    typer.echo("Type quit to leave the session.")
    while True:
        try:
            instruction = typer.prompt("rail-route")
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            return
        if instruction.strip().lower() in {"exit", "quit"}:
            return
        try:
            intent = parse_control_intent(instruction)
            result = (
                asyncio.run(execute_set_route_ui(intent))
                if intent.action is RailRouteAction.SET_ROUTE
                else controller.execute(intent)
            )
            typer.echo(result.message)
        except RailRouteError as error:
            typer.echo(f"error[{type(error).__name__}]: {error}", err=True)


def _openttd_adapter(
    *,
    enable_bridge: bool | None = None,
    prior_bridge_health: BridgeHealth | None = None,
    reject_bridge_identity_change: bool = False,
) -> OpenTTDAdapter:
    """Compose only the local adapter; never initialize a hosted provider."""
    configuration = openttd_configuration()
    client = OpenTTDAdminClient(configuration)
    bridge_enabled = configuration.gamescript_enabled if enable_bridge is None else enable_bridge
    bridge = (
        GameScriptBridgeClient(
            client,
            company_id=configuration.company_id,
            allow_writes=configuration.allow_gamescript_writes,
            timeout_seconds=configuration.observation_timeout_seconds,
            prior_health=prior_bridge_health,
            reject_instance_change=reject_bridge_identity_change,
        )
        if bridge_enabled
        else None
    )
    return OpenTTDAdapter(
        client,
        allow_writes=configuration.allow_writes,
        stale_days=configuration.stale_observation_threshold_days,
        action_timeout_seconds=configuration.action_timeout_seconds,
        bridge=bridge,
        allow_gamescript_writes=configuration.allow_gamescript_writes,
    )


async def _capture_openttd_observation() -> Observation:
    adapter = _openttd_adapter()
    await adapter.initialize()
    try:
        return await adapter.observe()
    finally:
        await adapter.shutdown()


@evaluate_app.command("product")
def evaluate_product(
    compiler_provider: Annotated[
        CompilerProviderName,
        typer.Option(
            "--compiler-provider",
            help="Model-backed compiler provider; explicitly select codex or openai.",
        ),
    ] = CompilerProviderName.NONE,
    decision_provider: Annotated[
        DecisionProviderName,
        typer.Option(
            "--decision-provider",
            help="Model-backed runtime provider; explicitly select codex or openai.",
        ),
    ] = DecisionProviderName.NONE,
    record_dir: Annotated[
        Path,
        typer.Option(
            "--record-dir",
            file_okay=False,
            help="Private directory for case results, raw exchanges, and manual review.",
        ),
    ] = Path("data/product-evaluation"),
    fixture: Annotated[
        Path,
        typer.Option("--fixture", exists=True, dir_okay=False),
    ] = DEFAULT_PRODUCT_EVALUATION_FIXTURE,
    compiler_model_name: Annotated[str | None, typer.Option("--compiler-model")] = None,
    decision_model_name: Annotated[str | None, typer.Option("--decision-model")] = None,
    input_cost_per_million: Annotated[
        float,
        typer.Option("--input-cost-per-million", min=0),
    ] = 0.0,
    output_cost_per_million: Annotated[
        float,
        typer.Option("--output-cost-per-million", min=0),
    ] = 0.0,
    max_runtime_iterations: Annotated[
        int,
        typer.Option("--max-runtime-iterations", min=1, max=20),
    ] = 8,
    max_compiler_calls: Annotated[int, typer.Option(min=1, max=100)] = 31,
    max_decision_calls: Annotated[int, typer.Option(min=0, max=500)] = 48,
    max_total_calls: Annotated[int, typer.Option(min=1, max=500)] = 79,
    total_wall_clock_seconds: Annotated[float, typer.Option(min=1)] = 3_600,
    stop_on_usage_limit: Annotated[bool, typer.Option()] = True,
    case: Annotated[
        list[str] | None,
        typer.Option("--case", help="Run only the named case; repeat to select several."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace completed case results instead of resuming."),
    ] = False,
) -> None:
    """Run the bounded product proving dataset; never selects a hosted provider implicitly."""
    if compiler_provider not in {CompilerProviderName.OPENAI, CompilerProviderName.CODEX}:
        _fail(
            ValueError("--compiler-provider codex or openai is required"),
            INVALID_INPUT,
        )
    if decision_provider not in {DecisionProviderName.OPENAI, DecisionProviderName.CODEX}:
        _fail(
            ValueError("--decision-provider codex or openai is required"),
            INVALID_INPUT,
        )
    compiler_name = (
        codex_model(compiler_model_name)
        if compiler_provider is CompilerProviderName.CODEX
        else compiler_model(compiler_model_name)
    )
    decision_name = (
        codex_model(decision_model_name)
        if decision_provider is DecisionProviderName.CODEX
        else decision_model(decision_model_name)
    )
    compiler_provider_value: Literal["openai", "codex"] = (
        "codex" if compiler_provider is CompilerProviderName.CODEX else "openai"
    )
    decision_provider_value: Literal["openai", "codex"] = (
        "codex" if decision_provider is DecisionProviderName.CODEX else "openai"
    )
    configuration = EvaluationRunConfiguration(
        compiler_provider=compiler_provider_value,
        decision_provider=decision_provider_value,
        compiler_model=compiler_name,
        decision_model=decision_name,
        input_cost_per_million_usd=input_cost_per_million,
        output_cost_per_million_usd=output_cost_per_million,
        max_runtime_iterations=max_runtime_iterations,
        max_output_tokens_per_call=(
            None
            if CompilerProviderName.CODEX is compiler_provider
            or DecisionProviderName.CODEX is decision_provider
            else PRODUCT_EVALUATION_MAX_OUTPUT_TOKENS
        ),
        cost_reporting=(
            "plan_allowance"
            if CompilerProviderName.CODEX is compiler_provider
            or DecisionProviderName.CODEX is decision_provider
            else "api_estimate"
        ),
        max_compiler_calls=max_compiler_calls,
        max_decision_calls=max_decision_calls,
        max_total_calls=max_total_calls,
        total_wall_clock_seconds=total_wall_clock_seconds,
        stop_on_usage_limit=stop_on_usage_limit,
    )

    def compiler_factory(item: ProductEvaluationCase) -> CompilerProvider:
        catalog = capability_catalog(item.adapter)
        prompt = compiler_prompt(catalog)
        provider: CompilerProvider
        if compiler_provider is CompilerProviderName.CODEX:
            provider = CodexCLICompilerProvider(
                model=compiler_name,
                prompt=prompt,
                timeout_seconds=codex_timeout_seconds(),
                executable=codex_executable(),
                temporary_directory_root=codex_temporary_directory_root(),
                preserve_debug_directory=codex_preserve_debug_directory(),
                maximum_stdout_bytes=codex_maximum_stdout_bytes(),
                maximum_stderr_bytes=codex_maximum_stderr_bytes(),
                capability_cache_seconds=codex_capability_cache_seconds(),
            )
        else:
            provider = OpenAICompilerProvider(
                model=compiler_name,
                prompt=prompt,
                max_retries=0,
                max_output_tokens=PRODUCT_EVALUATION_MAX_OUTPUT_TOKENS,
            )
        return RecordingCompilerProvider(
            provider,
            record_dir / "raw" / item.id / "compiler",
            prompt=prompt,
        )

    def decision_factory(item: ProductEvaluationCase) -> DecisionProvider:
        provider: DecisionProvider
        if decision_provider is DecisionProviderName.CODEX:
            provider = CodexCLIDecisionProvider(
                model=decision_name,
                timeout_seconds=codex_timeout_seconds(),
                executable=codex_executable(),
                temporary_directory_root=codex_temporary_directory_root(),
                preserve_debug_directory=codex_preserve_debug_directory(),
                maximum_stdout_bytes=codex_maximum_stdout_bytes(),
                maximum_stderr_bytes=codex_maximum_stderr_bytes(),
                capability_cache_seconds=codex_capability_cache_seconds(),
            )
        else:
            provider = OpenAIDecisionProvider(
                model=decision_name,
                timeout_seconds=decision_timeout_seconds(),
                transient_retries=0,
                max_output_tokens=PRODUCT_EVALUATION_MAX_OUTPUT_TOKENS,
            )
        return RecordingDecisionProvider(
            provider,
            record_dir / "raw" / item.id / "decisions",
        )

    try:
        aggregate = asyncio.run(
            run_product_evaluation(
                fixture_path=fixture,
                output_directory=record_dir,
                compiler_provider_factory=compiler_factory,
                decision_provider_factory=decision_factory,
                configuration=configuration,
                force=force,
                case_ids=frozenset(case or ()),
            )
        )
    except (OSError, CodexCLIError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)
    _emit(aggregate)


@openttd_app.command("capabilities")
def openttd_capabilities() -> None:
    """Display safe default capabilities without configuration or network access."""
    _emit(OpenTTDAdapterCapabilities())


@openttd_app.command("doctor")
def openttd_doctor() -> None:
    """Check local configuration and the Admin Network connection."""

    async def check() -> dict[str, object]:
        try:
            configuration = openttd_configuration()
        except (ValidationError, ValueError) as error:
            return {
                "configuration_valid": False,
                "connection_status": "not_checked",
                "error": str(error),
                "capabilities": OpenTTDAdapterCapabilities().model_dump(mode="json"),
            }
        executable_status = (
            "not_configured"
            if configuration.executable is None
            else "available"
            if configuration.executable.exists()
            else "unavailable"
        )
        script_status = (
            "not_required"
            if configuration.required_script_path is None
            else "available"
            if configuration.required_script_path.exists()
            else "unavailable"
        )
        client = OpenTTDAdminClient(configuration)
        try:
            await client.connect()
            return {
                "configuration_valid": True,
                "connection_status": "connected",
                "integration_method": "admin_network",
                "openttd_version": client.metadata.openttd_version,
                "protocol_version": client.metadata.protocol_version,
                "selected_company": configuration.company_id,
                "executable_status": executable_status,
                "required_component_status": script_status,
                "capabilities": OpenTTDAdapterCapabilities().model_dump(mode="json"),
            }
        except OpenTTDError as error:
            return {
                "configuration_valid": True,
                "connection_status": "unavailable",
                "selected_company": configuration.company_id,
                "executable_status": executable_status,
                "required_component_status": script_status,
                "error": str(error),
                "capabilities": OpenTTDAdapterCapabilities().model_dump(mode="json"),
            }
        finally:
            await client.close()

    _emit(asyncio.run(check()))


@openttd_app.command("observe")
def openttd_observe() -> None:
    """Capture one structured canonical observation."""
    try:
        _emit(asyncio.run(_capture_openttd_observation()))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_app.command("watch")
def openttd_watch(
    count: Annotated[int, typer.Option(min=1, help="Bounded observation count.")] = 10,
) -> None:
    """Poll local OpenTTD and print only supported resource changes."""

    async def watch() -> None:
        configuration = openttd_configuration()
        adapter = OpenTTDAdapter(OpenTTDAdminClient(configuration))
        previous: dict[str, str | int | None] | None = None
        await adapter.initialize()
        try:
            for index in range(count):
                observation = await adapter.observe()
                state = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
                current = {
                    "date": state.resources.date,
                    "cash": state.resources.cash,
                    "loan": state.resources.debt,
                    "income": state.resources.income,
                    "expenses": state.resources.expenses,
                    "profit": state.resources.profit,
                    "vehicle_count": state.resources.vehicle_count,
                    "alerts": None,
                }
                changes = (
                    current
                    if previous is None
                    else {key: value for key, value in current.items() if previous[key] != value}
                )
                if changes:
                    _emit({"sequence": observation.sequence, "changes": changes})
                previous = current
                if index + 1 < count:
                    await asyncio.sleep(configuration.polling_interval_seconds)
        finally:
            await adapter.shutdown()

    try:
        asyncio.run(watch())
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


async def _bridge_observation() -> tuple[Observation, BridgeHealth]:
    adapter = _openttd_adapter(enable_bridge=True)
    await adapter.initialize()
    try:
        observation = await adapter.observe()
        if adapter.bridge is None:
            raise ValueError("GameScript bridge composition is unavailable")
        return observation, adapter.bridge.health
    finally:
        await adapter.shutdown()


def _bridge_health_summary(health: BridgeHealth) -> dict[str, object]:
    payload = health.model_dump(mode="json", exclude={"world_snapshot"})
    world = health.world_snapshot
    payload["world_snapshot"] = (
        None
        if world is None
        else {
            "snapshot_id": world.snapshot_id,
            "complete": world.complete,
            "capture_started_game_date": world.capture_started_game_date,
            "capture_completed_game_date": world.capture_completed_game_date,
            "counts": {
                "companies": len(world.companies),
                "towns": len(world.towns),
                "industries": len(world.industries),
                "stations": len(world.stations),
                "vehicles": len(world.vehicles),
                "orders": len(world.orders),
                "cargos": len(world.cargos),
            },
        }
    )
    return payload


def _world_from_observation(observation: Observation) -> WorldSnapshot:
    state = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
    if state.world is None:
        raise ValueError("the running GameScript does not provide world snapshots")
    return state.world


async def capture_openttd_world_snapshot() -> WorldSnapshot:
    return (await _collect_analysis_snapshot()).snapshot


def _verification_from_health(
    health: BridgeHealth, *, synchronization_state: Literal["identity_verified", "synchronized"]
) -> SnapshotVerification:
    bridge_snapshot = health.snapshot
    company = None if bridge_snapshot is None else bridge_snapshot.company
    if (
        health.script_instance_id is None
        or health.capability_fingerprint is None
        or bridge_snapshot is None
        or company is None
        or health.active_company_context is None
        or health.last_sequence is None
        or health.openttd_version is None
        or health.bridge_protocol_version is None
        or health.script_version is None
    ):
        raise ValueError("bridge identity and company compatibility could not be established")
    world_id = health.script_instance_id
    return SnapshotVerification(
        identity=SnapshotIdentity(
            world_id=world_id,
            save_generation=bridge_snapshot.save_generation,
            capability_fingerprint=health.capability_fingerprint,
            observer_company_id=canonical_entity_id(world_id, "company", company.company_id),
            bridge_company_context=health.active_company_context,
        ),
        verified_at=datetime.now(UTC),
        bridge_sequence=health.last_sequence,
        synchronization_state=synchronization_state,
        openttd_version=health.openttd_version,
        bridge_protocol_version=health.bridge_protocol_version,
        script_version=health.script_version,
    )


async def _probe_openttd_snapshot_identity() -> SnapshotVerification:
    configuration = openttd_configuration()
    client = OpenTTDAdminClient(configuration)
    bridge = GameScriptBridgeClient(
        client,
        company_id=configuration.company_id,
        allow_writes=False,
        timeout_seconds=configuration.observation_timeout_seconds,
    )
    try:
        health = await bridge.verify_identity()
        return _verification_from_health(health, synchronization_state="identity_verified")
    finally:
        await bridge.close()


async def _collect_analysis_snapshot() -> AnalysisSnapshotAcquisition:
    started = perf_counter()
    observation, health = await _bridge_observation()
    duration = perf_counter() - started
    snapshot = _world_from_observation(observation)
    verification = _verification_from_health(health, synchronization_state="synchronized")
    expected = SnapshotIdentity.from_snapshot(
        snapshot,
        bridge_company_context=verification.identity.bridge_company_context,
    )
    if expected != verification.identity:
        raise ValueError("collected snapshot does not match synchronized bridge identity")
    return AnalysisSnapshotAcquisition(
        snapshot=snapshot,
        source=SnapshotSource.FRESH_COLLECTION,
        maximum_acceptable_age_seconds=0.0,
        collection_duration_seconds=duration,
        verification=verification,
        bridge_supported_actions=(
            () if health.capabilities is None else health.capabilities.supported_actions
        ),
    )


def _analysis_compiler(provider: AnalysisProviderName, model_name: str | None) -> AnalysisCompiler:
    if provider is AnalysisProviderName.NONE:
        return DeterministicAnalysisCompiler()
    if provider is AnalysisProviderName.CODEX:
        return CodexAnalysisCompiler(
            model=codex_model(model_name),
            timeout_seconds=codex_timeout_seconds(),
            executable=codex_executable(),
        )
    if provider is AnalysisProviderName.OPENAI:
        return OpenAIAnalysisCompiler(model=compiler_model(model_name))
    raise ValueError(f"unsupported analysis compiler provider: {provider!r}")


def _analysis_explainer(
    provider: AnalysisProviderName, model_name: str | None
) -> ExplanationProvider | None:
    if provider is AnalysisProviderName.NONE:
        return None
    if provider is AnalysisProviderName.CODEX:
        return CodexExplanationProvider(
            model=codex_model(model_name),
            timeout_seconds=codex_timeout_seconds(),
            executable=codex_executable(),
        )
    if provider is AnalysisProviderName.OPENAI:
        return OpenAIExplanationProvider(model=compiler_model(model_name))
    raise ValueError(f"unsupported explanation provider: {provider!r}")


async def _analysis_snapshot(
    path: Path | None,
    live: bool,
    fresh: bool = False,
    maximum_age_seconds: float | None = None,
) -> AnalysisSnapshotAcquisition:
    if path is not None and (live or fresh):
        raise ValueError("--snapshot cannot be combined with --live or --fresh")
    if maximum_age_seconds is not None and maximum_age_seconds < 0:
        raise ValueError("maximum snapshot age must not be negative")
    if path is not None:
        snapshot = WorldSnapshot.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
        age = max(0.0, (datetime.now(UTC) - snapshot.metadata.captured_at).total_seconds())
        if maximum_age_seconds is not None and age > maximum_age_seconds:
            raise ValueError("selected snapshot exceeds the requested maximum age")
        return AnalysisSnapshotAcquisition(
            snapshot=snapshot,
            source=SnapshotSource.SELECTED_FILE,
            maximum_acceptable_age_seconds=maximum_age_seconds,
            collection_duration_seconds=None,
        )

    maximum_age = (
        DEFAULT_ANALYSIS_MAXIMUM_SNAPSHOT_AGE_SECONDS
        if maximum_age_seconds is None
        else maximum_age_seconds
    )
    cache = SnapshotCache(analysis_session_directory() / "snapshot-cache.json")
    with cache.exclusive():
        if not (live or fresh or maximum_age == 0):
            candidate = cache.candidate_status(maximum_age)
            if candidate.status is SnapshotCacheStatus.REQUIRES_VERIFICATION:
                verification = await _probe_openttd_snapshot_identity()
                lookup = cache.load(
                    verification.identity,
                    maximum_age_seconds=maximum_age,
                )
                if lookup.status is SnapshotCacheStatus.HIT:
                    assert lookup.snapshot is not None
                    return AnalysisSnapshotAcquisition(
                        snapshot=lookup.snapshot,
                        source=SnapshotSource.COMPATIBLE_CACHE,
                        maximum_acceptable_age_seconds=maximum_age,
                        collection_duration_seconds=lookup.collection_duration_seconds,
                        verification=verification,
                    )
        acquired = await _collect_analysis_snapshot()
        verification = acquired.verification
        assert verification is not None
        cache.store(
            acquired.snapshot,
            identity=verification.identity,
            collection_duration_seconds=acquired.collection_duration_seconds or 0.0,
        )
        return AnalysisSnapshotAcquisition(
            snapshot=acquired.snapshot,
            source=acquired.source,
            maximum_acceptable_age_seconds=0.0 if live or fresh else maximum_age,
            collection_duration_seconds=acquired.collection_duration_seconds,
            verification=verification,
            bridge_supported_actions=acquired.bridge_supported_actions,
        )


def _analysis_session_store() -> AnalysisSessionStore:
    return AnalysisSessionStore(analysis_session_directory())


def _emit_analysis(
    response: AnalysisResponse,
    record: AnalysisSessionRecord,
    *,
    json_output: bool,
    detailed: bool,
    evidence: bool = False,
) -> None:
    if json_output:
        _emit(response)
        typer.echo(f"Analysis ID: {record.analysis_id}", err=True)
        return
    typer.echo(
        render_analysis(
            response,
            detailed=detailed,
            snapshot=record.snapshot,
            evidence=evidence,
        )
    )
    typer.echo("")
    typer.echo(f"Evidence available: sim-pilot analysis show {record.analysis_id}")


@app.command("ask")
def analysis_ask(
    question: Annotated[str, typer.Argument(help="Natural-language gameplay question.")],
    adapter: Annotated[AdapterId, typer.Option("--adapter")] = AdapterId.OPENTTD,
    compiler_provider: Annotated[
        AnalysisProviderName,
        typer.Option("--compiler-provider", help="none, codex, or openai; hosted use is explicit."),
    ] = AnalysisProviderName.NONE,
    explanation_provider: Annotated[
        AnalysisProviderName,
        typer.Option(
            "--explanation-provider", help="none, codex, or openai; hosted use is explicit."
        ),
    ] = AnalysisProviderName.NONE,
    snapshot_file: Annotated[
        Path | None,
        typer.Option("--snapshot", exists=True, dir_okay=False),
    ] = None,
    comparison_file: Annotated[
        Path | None,
        typer.Option("--comparison", exists=True, dir_okay=False),
    ] = None,
    live: Annotated[
        bool, typer.Option("--live", help="Collect a fresh read-only snapshot.")
    ] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    model: Annotated[str | None, typer.Option("--model")] = None,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    evidence: Annotated[bool, typer.Option("--evidence")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[
        float | None,
        typer.Option("--max-snapshot-age", min=0, help="Maximum reusable snapshot age in seconds."),
    ] = None,
    style: Annotated[ExplanationStyle, typer.Option("--style")] = ExplanationStyle.COMPACT,
) -> None:
    """Compile and answer a read-only gameplay question."""
    if adapter is not AdapterId.OPENTTD:
        _fail(
            ValueError("Phase 8B analysis currently supports only the OpenTTD adapter"),
            INVALID_INPUT,
        )

    progress = AnalysisProgress(
        quiet=quiet or json_output,
        emit=lambda message: typer.echo(message, err=True),
    )

    async def run() -> tuple[
        AnalysisCompilation, AnalysisResponse | None, AnalysisSnapshotAcquisition
    ]:
        if snapshot_file is None:
            progress.collecting()
        current_acquisition = await _analysis_snapshot(
            snapshot_file, live, fresh, maximum_snapshot_age
        )
        current = current_acquisition.snapshot
        comparison = (
            None
            if comparison_file is None
            else (await _analysis_snapshot(comparison_file, False)).snapshot
        )
        compiler = _analysis_compiler(compiler_provider, model)
        if compiler_provider is not AnalysisProviderName.NONE:
            progress.compiling()
        context = _analysis_session_store().compiler_context(
            current,
            comparison_snapshot_id=(
                None if comparison is None else comparison.metadata.snapshot_id
            ),
        )
        compilation = await compiler.compile(
            question,
            context=context,
        )
        if compilation.request is None:
            return compilation, None, current_acquisition
        request = compilation.request.model_copy(
            update={
                "maximum_findings": maximum_findings,
                "comparison_snapshot_id": (
                    compilation.request.comparison_snapshot_id
                    if comparison is None
                    else comparison.metadata.snapshot_id
                ),
            }
        )
        progress.analyzing(current)
        response = await AnalysisQueryService(
            AnalysisService(default_analyzer_registry())
        ).analyze_request(
            request,
            current,
            comparison=comparison,
            explanation_provider=_analysis_explainer(explanation_provider, model),
            style=style,
        )
        response = response.model_copy(update={"snapshot_metadata": current_acquisition.metadata()})
        return compilation, response, current_acquisition

    try:
        compilation, response, current_acquisition = asyncio.run(run())
        if response is None:
            if json_output:
                _emit(compilation)
            else:
                typer.echo(compilation.clarification or compilation.unsupported_reason)
            raise typer.Exit(INVALID_INPUT)
        record = _analysis_session_store().save(response, current_acquisition.snapshot)
        _emit_analysis(
            response,
            record,
            json_output=json_output,
            detailed=detailed,
            evidence=evidence,
        )
    except typer.Exit:
        raise
    except (
        AnalysisError,
        CodexCLIError,
        OSError,
        RuntimeError,
        ValidationError,
        ValueError,
    ) as error:
        _fail(error, INVALID_INPUT)


def _direct_analysis(
    analysis_type: AnalysisType,
    *,
    snapshot_file: Path | None,
    comparison_file: Path | None,
    live: bool,
    fresh: bool,
    maximum_snapshot_age: float | None,
    maximum_findings: int,
    entity_ids: tuple[str, ...],
    subject_type: AnalysisSubjectType | None,
    json_output: bool,
    detailed: bool,
    quiet: bool,
) -> None:
    progress = AnalysisProgress(
        quiet=quiet or json_output,
        emit=lambda message: typer.echo(message, err=True),
    )

    async def run() -> tuple[AnalysisResponse, WorldSnapshot]:
        if snapshot_file is None:
            progress.collecting()
        current_acquisition = await _analysis_snapshot(
            snapshot_file, live, fresh, maximum_snapshot_age
        )
        current = current_acquisition.snapshot
        comparison = (
            None
            if comparison_file is None
            else (await _analysis_snapshot(comparison_file, False)).snapshot
        )
        request = AnalysisRequest(
            analysis_type=analysis_type,
            question=f"Direct deterministic {analysis_type.value} analysis.",
            subject_type=subject_type if entity_ids else None,
            subject_ids=entity_ids,
            comparison_snapshot_id=(
                None if comparison is None else comparison.metadata.snapshot_id
            ),
            maximum_findings=maximum_findings,
        )
        progress.analyzing(current)
        response = (
            AnalysisService(default_analyzer_registry())
            .analyze(request, current, comparison)
            .model_copy(update={"snapshot_metadata": current_acquisition.metadata()})
        )
        return response, current

    try:
        response, current = asyncio.run(run())
        record = _analysis_session_store().save(response, current)
        _emit_analysis(response, record, json_output=json_output, detailed=detailed)
    except (AnalysisError, OSError, RuntimeError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)


def _direct_options(
    analysis_type: AnalysisType,
    snapshot_file: Path | None,
    comparison_file: Path | None,
    live: bool,
    fresh: bool,
    maximum_snapshot_age: float | None,
    maximum_findings: int,
    entity: list[str] | None,
    subject_type: AnalysisSubjectType | None,
    json_output: bool,
    detailed: bool,
    quiet: bool,
) -> None:
    _direct_analysis(
        analysis_type,
        snapshot_file=snapshot_file,
        comparison_file=comparison_file,
        live=live,
        fresh=fresh,
        maximum_snapshot_age=maximum_snapshot_age,
        maximum_findings=maximum_findings,
        entity_ids=tuple(entity or ()),
        subject_type=subject_type,
        json_output=json_output,
        detailed=detailed,
        quiet=quiet,
    )


@openttd_analyze_app.command("company")
def analyze_company(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    comparison_file: Annotated[Path | None, typer.Option("--comparison", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.COMPANY_HEALTH,
        snapshot_file,
        comparison_file,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        None,
        None,
        json_output,
        detailed,
        quiet,
    )


@openttd_analyze_app.command("vehicles")
def analyze_vehicles(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    comparison_file: Annotated[Path | None, typer.Option("--comparison", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    entity: Annotated[list[str] | None, typer.Option("--entity")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.VEHICLE_PERFORMANCE,
        snapshot_file,
        comparison_file,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        entity,
        AnalysisSubjectType.VEHICLE,
        json_output,
        detailed,
        quiet,
    )


@openttd_analyze_app.command("stations")
def analyze_stations(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    entity: Annotated[list[str] | None, typer.Option("--entity")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.STATION_PERFORMANCE,
        snapshot_file,
        None,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        entity,
        AnalysisSubjectType.STATION,
        json_output,
        detailed,
        quiet,
    )


@openttd_analyze_app.command("routes")
def analyze_routes(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    entity: Annotated[list[str] | None, typer.Option("--entity")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.ROUTE_PERFORMANCE,
        snapshot_file,
        None,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        entity,
        AnalysisSubjectType.ROUTE,
        json_output,
        detailed,
        quiet,
    )


@openttd_analyze_app.command("coverage")
def analyze_coverage(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.SERVICE_COVERAGE,
        snapshot_file,
        None,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        None,
        None,
        json_output,
        detailed,
        quiet,
    )


@openttd_analyze_app.command("changes")
def analyze_changes(
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    comparison_file: Annotated[Path | None, typer.Option("--comparison", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    maximum_findings: Annotated[int, typer.Option("--top", min=1, max=20)] = 5,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    detailed: Annotated[bool, typer.Option("--detailed")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    fresh: Annotated[bool, typer.Option("--fresh")] = False,
    maximum_snapshot_age: Annotated[float | None, typer.Option("--max-snapshot-age", min=0)] = None,
) -> None:
    _direct_options(
        AnalysisType.WORLD_CHANGES,
        snapshot_file,
        comparison_file,
        live,
        fresh,
        maximum_snapshot_age,
        maximum_findings,
        None,
        None,
        json_output,
        detailed,
        quiet,
    )


@analysis_app.command("show")
def analysis_show(
    analysis_id: Annotated[str | None, typer.Argument()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the latest or selected analysis and its finding IDs."""
    try:
        record = _analysis_session_store().load(analysis_id)
        _emit(record) if json_output else typer.echo(render_session_summary(record))
    except (OSError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)


@analysis_app.command("evidence")
def analysis_evidence(analysis_id: str, finding_id: str) -> None:
    """Explain the evidence behind one previous finding."""
    try:
        record = _analysis_session_store().load(analysis_id)
        typer.echo(render_finding_evidence(record, finding_id))
    except (OSError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)


@analysis_app.command("inspect")
def analysis_inspect(
    analysis_id: str,
    finding_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a named finding target and report the live inspection capability."""
    try:
        record = _analysis_session_store().load(analysis_id)
        action = resolve_inspection_action(record, finding_id)
        current = asyncio.run(_analysis_snapshot(None, True))
        verification = current.verification
        if verification is None:
            raise EntityInspectionError(
                "missing_identity", "fresh collection did not establish bridge identity"
            )
        result = evaluate_unsupported_inspection(
            action,
            current.snapshot,
            bridge_company_context=verification.identity.bridge_company_context,
            supported_actions=current.bridge_supported_actions,
        )
        _emit(result) if json_output else typer.echo(render_inspection_result(result))
    except (
        EntityInspectionError,
        OpenTTDError,
        OSError,
        RuntimeError,
        ValidationError,
        ValueError,
    ) as error:
        _fail(error, INVALID_INPUT)


@analysis_app.command("entity")
def analysis_entity(
    analysis_id: str,
    subject: AnalysisSubjectType,
    reference: str,
) -> None:
    """Inspect one entity from a previous analysis snapshot."""
    try:
        record = _analysis_session_store().load(analysis_id)
        typer.echo(
            render_entity(
                record.snapshot,
                subject,
                reference,
                record.response.findings,
            )
        )
    except (OSError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)


def _openttd_entity(
    subject: AnalysisSubjectType,
    reference: str,
    snapshot_file: Path | None,
    live: bool,
) -> None:
    try:
        snapshot = asyncio.run(_analysis_snapshot(snapshot_file, live)).snapshot
        typer.echo(render_entity(snapshot, subject, reference))
    except (OpenTTDError, OSError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)


@openttd_app.command("vehicle")
def openttd_vehicle(
    reference: str,
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
) -> None:
    _openttd_entity(AnalysisSubjectType.VEHICLE, reference, snapshot_file, live)


@openttd_app.command("station")
def openttd_station(
    reference: str,
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
) -> None:
    _openttd_entity(AnalysisSubjectType.STATION, reference, snapshot_file, live)


@openttd_app.command("route")
def openttd_route(
    reference: str,
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
) -> None:
    _openttd_entity(AnalysisSubjectType.ROUTE, reference, snapshot_file, live)


@openttd_app.command("industry")
def openttd_industry(
    reference: str,
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
) -> None:
    _openttd_entity(AnalysisSubjectType.INDUSTRY, reference, snapshot_file, live)


@openttd_app.command("town")
def openttd_town(
    reference: str,
    snapshot_file: Annotated[Path | None, typer.Option("--snapshot", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
) -> None:
    _openttd_entity(AnalysisSubjectType.TOWN, reference, snapshot_file, live)


def _emit_world_collection(collection: str, json_output: bool) -> None:
    try:
        world = asyncio.run(capture_openttd_world_snapshot())
        if json_output:
            items = getattr(world, "companies" if collection == "company" else collection)
            _emit([item.model_dump(mode="json") for item in items])
        else:
            typer.echo(render_world_collection(world, collection))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_app.command("world")
def openttd_world(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """Display the canonical world snapshot and its coverage."""
    try:
        world = asyncio.run(capture_openttd_world_snapshot())
        _emit(world) if json_output else typer.echo(render_world_summary(world))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_app.command("towns")
def openttd_towns(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List observed towns."""
    _emit_world_collection("towns", json_output)


@openttd_app.command("industries")
def openttd_industries(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List observed industries."""
    _emit_world_collection("industries", json_output)


@openttd_app.command("stations")
def openttd_stations(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List selected-company stations."""
    _emit_world_collection("stations", json_output)


@openttd_app.command("vehicles")
def openttd_vehicles(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List selected-company vehicles."""
    _emit_world_collection("vehicles", json_output)


@openttd_app.command("company")
def openttd_company(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List observed companies."""
    _emit_world_collection("company", json_output)


@openttd_app.command("routes")
def openttd_routes(
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """List deterministically inferred routes."""
    _emit_world_collection("routes", json_output)


@openttd_app.command("diff")
def openttd_diff(
    wait_seconds: Annotated[
        float,
        typer.Option(min=0.0, help="Seconds between the two snapshots."),
    ] = 1.0,
    json_output: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """Capture two snapshots and display deterministic changes."""

    async def capture() -> WorldSnapshot:
        adapter = _openttd_adapter(enable_bridge=True)
        await adapter.initialize()
        try:
            first = _world_from_observation(await adapter.observe())
            await asyncio.sleep(wait_seconds)
            second = _world_from_observation(await adapter.observe())
            if second.changes_from_snapshot_id != first.metadata.snapshot_id:
                raise ValueError("adapter did not link consecutive world snapshots")
            return second
        finally:
            await adapter.shutdown()

    try:
        world = asyncio.run(capture())
        if json_output:
            _emit([change.model_dump(mode="json") for change in world.changes])
        else:
            typer.echo(render_world_changes(world.changes))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_app.command("doctor")
def openttd_bridge_doctor() -> None:
    """Connect, negotiate, synchronize, and display bridge health."""
    try:
        observation, health = asyncio.run(_bridge_observation())
        state = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
        _emit(
            {
                "admin_protocol_version": state.game.connection.protocol_version,
                "openttd_version": state.game.connection.openttd_version,
                "selected_company": state.game.company.company_id,
                "bridge": _bridge_health_summary(health),
                "snapshot_age_seconds": (
                    None
                    if health.last_snapshot_at is None
                    else max(
                        0.0,
                        (datetime.now(UTC) - health.last_snapshot_at).total_seconds(),
                    )
                ),
            }
        )
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_app.command("capabilities")
def openttd_bridge_capabilities() -> None:
    """Display capabilities negotiated from the running GameScript."""
    try:
        _, health = asyncio.run(_bridge_observation())
        _emit(
            {
                "capability_fingerprint": health.capability_fingerprint,
                "capabilities": (
                    None
                    if health.capabilities is None
                    else health.capabilities.model_dump(mode="json")
                ),
            }
        )
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_app.command("observe")
def openttd_bridge_observe() -> None:
    """Capture one combined Admin Network and GameScript observation."""
    try:
        observation, _ = asyncio.run(_bridge_observation())
        _emit(observation)
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_app.command("sync")
def openttd_bridge_sync() -> None:
    """Force a full bridge resynchronization and display its identity."""
    try:
        _, health = asyncio.run(_bridge_observation())
        _emit(_bridge_health_summary(health))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_app.command("watch")
def openttd_bridge_watch(
    count: Annotated[int, typer.Option(min=1, help="Bounded snapshot count.")] = 10,
) -> None:
    """Print a bounded stream of synchronized full snapshots."""

    async def watch() -> None:
        configuration = openttd_configuration()
        adapter = _openttd_adapter(enable_bridge=True)
        await adapter.initialize()
        try:
            for index in range(count):
                observation = await adapter.observe()
                state = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
                _emit(
                    {
                        "observation_sequence": observation.sequence,
                        "game_date": observation.tick,
                        "bridge_sequence": (
                            None if state.bridge is None else state.bridge.last_sequence
                        ),
                        "snapshot": (
                            None
                            if state.bridge is None or state.bridge.snapshot is None
                            else state.bridge.snapshot.model_dump(mode="json")
                        ),
                    }
                )
                if index + 1 < count:
                    await asyncio.sleep(configuration.polling_interval_seconds)
        finally:
            await adapter.shutdown()

    try:
        asyncio.run(watch())
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_bridge_action_app.command("set-company-name")
def openttd_bridge_set_company_name(name: str) -> None:
    """Run the sole verified GameScript mutation with fresh-snapshot verification."""

    async def run() -> dict[str, object]:
        adapter = _openttd_adapter(enable_bridge=True)
        verifier = ActionVerifier()
        action = Action(
            type="set_company_name",
            parameters={"name": name},
            expected_effect=f"Set the selected OpenTTD company name to {name!r}.",
        )
        await adapter.initialize()
        try:
            before = await adapter.observe()
            validation = await adapter.validate(action)
            if not validation.valid:
                raise ValueError(validation.message)
            result = await adapter.execute(action)
            after = await adapter.observe()
            verification = verifier.verify(before, action, result, after, validation.estimated_cost)
            if not verification.verified:
                raise ValueError("; ".join(verification.reasons))
            return {
                "action": action.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "verification": verification.model_dump(mode="json"),
                "before": before.model_dump(mode="json"),
                "after": after.model_dump(mode="json"),
            }
        finally:
            await adapter.shutdown()

    try:
        _emit(asyncio.run(run()))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@openttd_action_app.command("set-server-name")
def openttd_set_server_name(name: str) -> None:
    """Set and independently verify the server name without initializing hosted providers."""

    async def run() -> dict[str, object]:
        adapter = _openttd_adapter()
        verifier = ActionVerifier()
        action = Action(
            type="set_server_name",
            parameters={"name": name},
            expected_effect=f"Set the observed OpenTTD server name to {name!r}.",
        )
        await adapter.initialize()
        try:
            before = await adapter.observe()
            validation = await adapter.validate(action)
            if not validation.valid:
                raise ValueError(validation.message)
            result = await adapter.execute(action)
            after = await adapter.observe()
            verification = verifier.verify(before, action, result, after, validation.estimated_cost)
            if not verification.verified:
                raise ValueError("; ".join(verification.reasons))
            return {
                "action": action.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "verification": verification.model_dump(mode="json"),
                "before": before.model_dump(mode="json"),
                "after": after.model_dump(mode="json"),
            }
        finally:
            await adapter.shutdown()

    try:
        _emit(asyncio.run(run()))
    except (OpenTTDError, ValidationError, ValueError) as error:
        _fail(error, OPENTTD_FAILURE)


@db_app.command("upgrade")
def db_upgrade(ctx: typer.Context) -> None:
    try:
        upgrade_database(_context(ctx).url)
    except Exception as error:
        _fail(error, MIGRATION_FAILURE)
    typer.echo("database upgraded")


@task_app.command("create")
def task_create(
    ctx: typer.Context,
    specification: Annotated[
        Path | None, typer.Option("--spec", exists=True, dir_okay=False)
    ] = None,
    target_cash: Annotated[float, typer.Option(min=0)] = 520_000,
    task_id: Annotated[UUID | None, typer.Option()] = None,
    instruction: Annotated[str | None, typer.Option("--instruction", "-i")] = None,
    provider: Annotated[
        CompilerProviderName,
        typer.Option("--provider", help="Compiler provider; model access is always explicit."),
    ] = CompilerProviderName.NONE,
    model: Annotated[str | None, typer.Option("--model")] = None,
    record_dir: Annotated[
        Path | None,
        typer.Option(
            "--record-dir",
            file_okay=False,
            help="Opt in to local JSON recordings containing the instruction and full prompt.",
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    adapter: Annotated[AdapterId, typer.Option("--adapter")] = AdapterId.REFERENCE,
) -> None:
    try:
        registration = adapter_registration(adapter)
        if not registration.runtime_factory_available:
            raise ValueError(
                registration.unavailable_reason
                or f"task runtime is unavailable for {adapter.value!r}"
            )
        if specification is not None and instruction is not None:
            raise ValueError("--spec and --instruction are mutually exclusive")
        if instruction is not None:
            result = asyncio.run(
                _intent_compiler(provider, record_dir, adapter, model).compile(instruction)
            )
            _emit(result)
            if result.report.validation_status is not ValidationStatus.VALID:
                raise ValueError(
                    f"instruction did not compile: {result.report.validation_status.value}"
                )
            if result.specification is None:
                raise ValueError("valid compilation returned no task specification")
            if not yes and not typer.confirm("Persist this compiled task?"):
                typer.echo("task not persisted")
                return
            spec = result.specification
        elif specification is None:
            spec = TaskSpecification(
                objective=Objective(
                    type=ObjectiveType.REACH_RESOURCE,
                    description=f"Reach {target_cash:g} cash.",
                    parameters={"resource": "cash", "target": target_cash},
                ),
                authority=AuthorityPolicy(),
            )
        else:
            spec = TaskSpecification.model_validate_json(specification.read_text())
        spec = spec.model_copy(update={"adapter_type": adapter})
        now = datetime.now(UTC)
        task = Task(
            id=task_id or uuid4(),
            status=TaskStatus.PENDING,
            specification=spec,
            created_at=now,
            updated_at=now,
        )
        engine, runtime = _runtime(ctx)
        try:
            created = runtime.create_task(task)
        finally:
            engine.dispose()
        _emit(created)
    except (
        OSError,
        CodexCLIError,
        CompilerError,
        ValidationError,
        ValueError,
        PersistenceError,
    ) as error:
        _fail(error, INVALID_INPUT)


@task_app.command("compile")
def task_compile(
    instruction: Annotated[str | None, typer.Option("--instruction", "-i")] = None,
    provider: Annotated[
        CompilerProviderName,
        typer.Option("--provider", help="Compiler provider; model access is always explicit."),
    ] = CompilerProviderName.NONE,
    model: Annotated[str | None, typer.Option("--model")] = None,
    record_dir: Annotated[
        Path | None,
        typer.Option(
            "--record-dir",
            file_okay=False,
            help="Opt in to local JSON recordings containing the instruction and full prompt.",
        ),
    ] = None,
    adapter: Annotated[AdapterId, typer.Option("--adapter")] = AdapterId.REFERENCE,
) -> None:
    text = instruction if instruction is not None else typer.prompt("Prompt")
    try:
        result = asyncio.run(_intent_compiler(provider, record_dir, adapter, model).compile(text))
        _emit(result)
    except (OSError, CodexCLIError, CompilerError, ValidationError, ValueError) as error:
        _fail(error, INVALID_INPUT)
    if result.report.validation_status is not ValidationStatus.VALID:
        raise typer.Exit(INVALID_INPUT)


async def _run_task(
    ctx: typer.Context,
    task_id: UUID,
    iterations: int | None,
    decision_provider_name: DecisionProviderName,
    decision_model_name: str | None,
    recording_directory: Path | None,
) -> int:
    decision_provider = _decision_provider(
        decision_provider_name, recording_directory, decision_model_name
    )
    engine, runtime = _runtime(ctx)
    try:
        starting_sequence = runtime.reconstruct(task_id).task.sequence
        outcome = await runtime.resume(
            task_id,
            _restore,
            decision_provider,
            iteration_budget=iterations,
        )
        context = runtime.reconstruct(task_id)
        _emit(outcome)
        decision_event = next(
            (
                event
                for event in reversed(context.events)
                if event.sequence > starting_sequence
                and event.event_type.value == "decision_generated"
            ),
            None,
        )
        if decision_event is not None:
            metadata = decision_event.payload.get("provider_metadata")
            action = decision_event.payload.get("action")
            _emit(
                {
                    "decision_metadata": {
                        "decision_type": decision_event.payload.get("type"),
                        "selected_action": (
                            action.get("type") if isinstance(action, dict) else None
                        ),
                        "provider": metadata,
                    }
                }
            )
        return _exit_for(outcome.status, context.unresolved_attempt is not None)
    finally:
        engine.dispose()


@task_app.command("run")
def task_run(
    ctx: typer.Context,
    task_id: UUID,
    iterations: Annotated[int | None, typer.Option(min=1)] = None,
    decision_provider: Annotated[
        DecisionProviderName,
        typer.Option(
            "--decision-provider",
            help="Runtime decision provider; model access is always explicit.",
        ),
    ] = DecisionProviderName.NONE,
    decision_model_name: Annotated[str | None, typer.Option("--decision-model")] = None,
    record_dir: Annotated[
        Path | None,
        typer.Option(
            "--record-dir",
            file_okay=False,
            help="Opt in to local decision context and response recordings.",
        ),
    ] = None,
) -> None:
    try:
        code = asyncio.run(
            _run_task(
                ctx,
                task_id,
                iterations,
                decision_provider,
                decision_model_name,
                record_dir,
            )
        )
    except (CodexCLIError, DecisionProviderError) as error:
        _fail(error, INVALID_INPUT)
    except (PersistenceError, DurablePersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    raise typer.Exit(code)


@task_app.command("resume")
def task_resume(
    ctx: typer.Context,
    task_id: UUID,
    iterations: Annotated[int | None, typer.Option(min=1)] = None,
    decision_provider: Annotated[
        DecisionProviderName,
        typer.Option(
            "--decision-provider",
            help="Runtime decision provider; model access is always explicit.",
        ),
    ] = DecisionProviderName.NONE,
    decision_model_name: Annotated[str | None, typer.Option("--decision-model")] = None,
    record_dir: Annotated[
        Path | None,
        typer.Option("--record-dir", file_okay=False),
    ] = None,
) -> None:
    task_run(ctx, task_id, iterations, decision_provider, decision_model_name, record_dir)


@task_app.command("show")
def task_show(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        context = runtime.reconstruct(task_id)
        _emit(
            {
                "task": context.task.model_dump(mode="json"),
                "checkpoint": (
                    None
                    if context.checkpoint is None
                    else context.checkpoint.model_dump(mode="json")
                ),
                "pending_approval": (
                    None
                    if context.pending_approval is None
                    else context.pending_approval.model_dump(mode="json")
                ),
                "recovery": (
                    None
                    if context.unresolved_attempt is None
                    else context.unresolved_attempt.model_dump(mode="json")
                ),
            }
        )
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("events")
def task_events(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        for event in runtime.reconstruct(task_id).events:
            typer.echo(event.model_dump_json())
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


def _approval_task_id(ctx: typer.Context, approval_id: UUID) -> UUID:
    engine = create_sqlite_engine(_context(ctx).url)
    task_id: UUID | None = None
    try:
        with SQLiteUnitOfWork(engine) as uow:
            task_id = uow.approvals.get(approval_id).approval.task_id
    finally:
        engine.dispose()
    if task_id is None:
        raise RuntimeError("approval lookup returned no task")
    return task_id


@task_app.command("approve")
def task_approve(ctx: typer.Context, approval_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        approved = runtime.approve(_approval_task_id(ctx, approval_id))
        _emit(approved)
    except (PersistenceError, ValueError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("deny")
def task_deny(ctx: typer.Context, approval_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        denied = runtime.deny(_approval_task_id(ctx, approval_id))
        _emit(denied)
    except (PersistenceError, ValueError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("cancel")
def task_cancel(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        runtime.cancel(task_id)
        typer.echo("task cancelled")
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


def _snapshot(path: Path | None) -> AdapterSnapshot | None:
    return None if path is None else AdapterSnapshot.model_validate_json(path.read_text())


@recovery_app.command("show")
def recovery_show(
    ctx: typer.Context,
    task_id: UUID,
    snapshot: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    engine, runtime = _runtime(ctx)
    try:
        report = asyncio.run(runtime.inspect_recovery(task_id, _snapshot(snapshot)))
        _emit({"recovery": None} if report is None else report)
    except (OSError, ValidationError, ValueError, PersistenceError) as error:
        _fail(error)
    finally:
        engine.dispose()


@recovery_app.command("resolve")
def recovery_resolve(
    ctx: typer.Context,
    task_id: UUID,
    resolution: RecoveryResolution,
    snapshot: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    engine, runtime = _runtime(ctx)
    try:
        asyncio.run(
            runtime.resolve_recovery(task_id, resolution, current_snapshot=_snapshot(snapshot))
        )
        typer.echo("recovery resolved")
    except (OSError, ValidationError, ValueError, PersistenceError) as error:
        _fail(error)
    finally:
        engine.dispose()
