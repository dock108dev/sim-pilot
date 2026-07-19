"""Minimal durable Task 4C command-line interface."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, NoReturn
from uuid import UUID, uuid4

import typer
from pydantic import ValidationError
from sqlalchemy import Engine

from sim_pilot.adapters.base import AdapterSnapshot, SimulationAdapter
from sim_pilot.adapters.openttd import OpenTTDAdapter, OpenTTDReadOnlyAdapter
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.config import (
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
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    Observation,
    Task,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.domain.models import JsonValue
from sim_pilot.intent_compiler import (
    CompilerError,
    CompilerProvider,
    IntentCompiler,
    ValidationStatus,
)
from sim_pilot.intent_compiler.prompt import (
    OPENTTD_CAPABILITIES,
    REFERENCE_CAPABILITIES,
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

app = typer.Typer(help="Durable local runtime for the deterministic reference simulation.")
db_app = typer.Typer(help="Manage durable schema state.")
task_app = typer.Typer(help="Create and operate structured tasks.")
recovery_app = typer.Typer(help="Inspect and resolve interrupted action attempts.")
openttd_app = typer.Typer(help="Observe a local OpenTTD 15.3 game through its admin port.")
openttd_action_app = typer.Typer(help="Run a directly validated and verified OpenTTD action.")
openttd_bridge_app = typer.Typer(help="Operate the versioned OpenTTD GameScript bridge.")
openttd_bridge_action_app = typer.Typer(help="Run a verified, explicitly enabled bridge action.")
evaluate_app = typer.Typer(help="Run explicitly authorized product evaluation exercises.")
app.add_typer(db_app, name="db")
app.add_typer(task_app, name="task")
app.add_typer(openttd_app, name="openttd")
app.add_typer(evaluate_app, name="evaluate")
openttd_app.add_typer(openttd_action_app, name="action")
openttd_app.add_typer(openttd_bridge_app, name="bridge")
openttd_bridge_app.add_typer(openttd_bridge_action_app, name="action")
task_app.add_typer(recovery_app, name="recovery")

DEFAULT_PRODUCT_EVALUATION_FIXTURE = Path("tests/fixtures/product_evaluation_instructions.json")
PRODUCT_EVALUATION_MAX_OUTPUT_TOKENS = 2048


@dataclass
class CLIContext:
    url: str


class CompilerProviderName(StrEnum):
    NONE = "none"
    OPENAI = "openai"
    CODEX = "codex"


class DecisionProviderName(StrEnum):
    NONE = "none"
    SCRIPTED = "scripted"
    OPENAI = "openai"
    CODEX = "codex"


class AdapterName(StrEnum):
    REFERENCE = "reference"
    OPENTTD = "openttd"


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
    return engine, RuntimeEngine(unit_of_work_factory=lambda: SQLiteUnitOfWork(engine))


def _intent_compiler(
    provider_name: CompilerProviderName,
    recording_directory: Path | None,
    adapter_name: AdapterName = AdapterName.REFERENCE,
    model_name: str | None = None,
) -> IntentCompiler:
    catalog = (
        OPENTTD_CAPABILITIES if adapter_name is AdapterName.OPENTTD else REFERENCE_CAPABILITIES
    )
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
    else:
        provider = NoProviderConfigured()
    if recording_directory is not None:
        provider = RecordingCompilerProvider(provider, recording_directory, prompt=prompt)
    return IntentCompiler(provider, catalog)


def _restore(context: ReconstructedRuntimeContext) -> SimulationAdapter:
    if _is_openttd_specification(context.task.specification):
        prior_health: BridgeHealth | None = None
        if context.checkpoint is not None:
            raw = context.checkpoint.state.get("bridge")
            if isinstance(raw, dict):
                prior_health = BridgeHealth.model_validate(raw, strict=True)
        return _openttd_adapter(
            prior_bridge_health=prior_health,
            reject_bridge_identity_change=prior_health is not None,
        )
    if context.checkpoint is None:
        return ReferenceSimulationAdapter()
    return ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot())


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
    else:
        provider = ReferenceDemoDecisionProvider()
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
    if hasattr(value, "model_dump_json"):
        typer.echo(value.model_dump_json(indent=2))  # type: ignore[union-attr]
    else:
        typer.echo(json.dumps(value, indent=2, default=str))


def _fail(error: Exception, code: int = PERSISTENCE_FAILURE) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(code)


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


def _is_openttd_specification(specification: TaskSpecification) -> bool:
    return specification.adapter_type == "openttd"


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
            help="Hosted compiler provider; explicitly select codex or openai.",
        ),
    ] = CompilerProviderName.NONE,
    decision_provider: Annotated[
        DecisionProviderName,
        typer.Option(
            "--decision-provider",
            help="Hosted runtime provider; explicitly select codex or openai.",
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
        catalog = OPENTTD_CAPABILITIES if item.adapter == "openttd" else REFERENCE_CAPABILITIES
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
        adapter = OpenTTDReadOnlyAdapter(OpenTTDAdminClient(configuration))
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
                "bridge": health.model_dump(mode="json"),
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
        _emit(health)
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
        typer.Option("--provider", help="Compiler provider; hosted access is always explicit."),
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
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = AdapterName.REFERENCE,
) -> None:
    try:
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
        spec = spec.model_copy(update={"adapter_type": adapter.value})
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
        typer.Option("--provider", help="Compiler provider; hosted access is always explicit."),
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
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = AdapterName.REFERENCE,
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
            help="Runtime decision provider; hosted access is always explicit.",
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
            help="Runtime decision provider; hosted access is always explicit.",
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
