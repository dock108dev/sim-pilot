"""Bounded, opt-in product proving runner for hosted compiler and decision providers."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import Task, TaskStatus
from sim_pilot.intent_compiler import (
    CompilationResult,
    CompilerCapabilityCatalog,
    CompilerProvider,
    IntentCompiler,
)
from sim_pilot.intent_compiler.models import CompilerProviderResult, ValidationStatus
from sim_pilot.intent_compiler.prompt import OPENTTD_CAPABILITIES, REFERENCE_CAPABILITIES
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage
from sim_pilot.runtime import RuntimeEngine
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.models import RuntimeEventType

EvaluationAdapter = Literal["reference", "openttd"]
EvaluationCategory = Literal[
    "clear_supported",
    "informal_supported",
    "ambiguous",
    "contradictory",
    "unsupported",
    "openttd_specific",
]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1


class ProductEvaluationCase(EvaluationModel):
    id: str = Field(pattern=r"^[a-z]+-[0-9]{3}$")
    category: EvaluationCategory
    instruction: str = Field(min_length=1)
    adapter: EvaluationAdapter
    expected_statuses: tuple[ValidationStatus, ...] = Field(min_length=1)
    run_runtime: bool


class EvaluationCall(EvaluationModel):
    kind: Literal["compiler", "decision"]
    provider: str
    model: str | None = None
    request_id: str | None = None
    latency_ms: float = Field(ge=0)
    token_usage: ProviderTokenUsage | None = None
    estimated_cost_usd: float = Field(ge=0)


class EvaluationRuntimeResult(EvaluationModel):
    attempted: bool
    status: str | None = None
    iterations: int = Field(default=0, ge=0)
    decisions: int = Field(default=0, ge=0)
    actions_selected: int = Field(default=0, ge=0)
    selected_actions: tuple[str, ...] = ()
    actions_executed: int = Field(default=0, ge=0)
    actions_rejected: int = Field(default=0, ge=0)
    policy_rejections: int = Field(default=0, ge=0)
    adapter_rejections: int = Field(default=0, ge=0)
    intervention_required: bool = False
    reason: str | None = None


class ProductEvaluationResult(EvaluationModel):
    case_id: str
    category: EvaluationCategory
    instruction: str
    adapter: EvaluationAdapter
    expected_statuses: tuple[ValidationStatus, ...]
    expected_outcome_matched: bool
    compilation_status: ValidationStatus | None = None
    specification: dict[str, object] | None = None
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported_requests: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    validation_errors: tuple[dict[str, object], ...] = ()
    semantic_validation_passed: bool
    runtime: EvaluationRuntimeResult
    calls: tuple[EvaluationCall, ...] = ()
    compiler_call_count: int = Field(ge=0)
    decision_call_count: int = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    failure_category: str | None = None
    failure_message: str | None = None
    manual_rating: Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"] | None = None
    reviewer_notes: str | None = None


class EvaluationRunConfiguration(EvaluationModel):
    compiler_provider: Literal["openai"]
    decision_provider: Literal["openai"]
    compiler_model: str = Field(min_length=1)
    decision_model: str = Field(min_length=1)
    input_cost_per_million_usd: float = Field(ge=0)
    output_cost_per_million_usd: float = Field(ge=0)
    max_runtime_iterations: int = Field(gt=0)
    max_output_tokens_per_call: int = Field(gt=0)


class _TrackingCompilerProvider:
    def __init__(self, provider: CompilerProvider) -> None:
        self._provider = provider
        self.calls: list[tuple[ProviderMetadata, float]] = []
        self.attempts = 0

    async def compile(self, instruction: str) -> CompilerProviderResult:
        self.attempts += 1
        started = perf_counter()
        result = await self._provider.compile(instruction)
        elapsed = (perf_counter() - started) * 1000
        self.calls.append((result.metadata, elapsed))
        return result


class _TrackingDecisionProvider:
    def __init__(self, provider: DecisionProvider) -> None:
        self._provider = provider
        self.calls: list[tuple[ProviderMetadata, float]] = []
        self.attempts = 0

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        self.attempts += 1
        started = perf_counter()
        result = await self._provider.decide(context)
        elapsed = (perf_counter() - started) * 1000
        self.calls.append((result.metadata, elapsed))
        return result


def load_evaluation_cases(path: Path) -> tuple[ProductEvaluationCase, ...]:
    cases = tuple(
        TypeAdapter(list[ProductEvaluationCase]).validate_json(
            path.read_text(encoding="utf-8"), strict=True
        )
    )
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("product evaluation case ids must be unique")
    return cases


def _catalog(case: ProductEvaluationCase) -> CompilerCapabilityCatalog:
    return OPENTTD_CAPABILITIES if case.adapter == "openttd" else REFERENCE_CAPABILITIES


def _secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _atomic_write(path: Path, content: str) -> None:
    _secure_directory(path.parent)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _estimated_cost(
    usage: ProviderTokenUsage | None,
    configuration: EvaluationRunConfiguration,
) -> float:
    if usage is None:
        return 0.0
    return (
        usage.input_tokens * configuration.input_cost_per_million_usd
        + usage.output_tokens * configuration.output_cost_per_million_usd
    ) / 1_000_000


def _call(
    kind: Literal["compiler", "decision"],
    metadata: ProviderMetadata,
    elapsed_ms: float,
    configuration: EvaluationRunConfiguration,
) -> EvaluationCall:
    return EvaluationCall(
        kind=kind,
        provider=metadata.provider,
        model=metadata.model,
        request_id=metadata.request_id,
        latency_ms=metadata.latency_ms if metadata.latency_ms is not None else elapsed_ms,
        token_usage=metadata.token_usage,
        estimated_cost_usd=_estimated_cost(metadata.token_usage, configuration),
    )


def _safe_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", message)[:500]


def _result_totals(calls: Iterable[EvaluationCall]) -> tuple[float, int, int, float]:
    materialized = tuple(calls)
    return (
        sum(item.latency_ms for item in materialized),
        sum(item.token_usage.input_tokens for item in materialized if item.token_usage),
        sum(item.token_usage.output_tokens for item in materialized if item.token_usage),
        sum(item.estimated_cost_usd for item in materialized),
    )


async def _evaluate_case(
    case: ProductEvaluationCase,
    compiler_provider: CompilerProvider,
    decision_provider: DecisionProvider,
    configuration: EvaluationRunConfiguration,
) -> ProductEvaluationResult:
    tracked_compiler = _TrackingCompilerProvider(compiler_provider)
    tracked_decisions = _TrackingDecisionProvider(decision_provider)
    compilation: CompilationResult | None = None
    runtime_result = EvaluationRuntimeResult(attempted=False)
    failure_category: str | None = None
    failure_message: str | None = None
    try:
        compilation = await IntentCompiler(tracked_compiler, _catalog(case)).compile(
            case.instruction
        )
        if (
            case.run_runtime
            and case.adapter == "reference"
            and compilation.report.validation_status is ValidationStatus.VALID
            and compilation.specification is not None
        ):
            now = datetime.now(UTC)
            task = Task(
                id=uuid5(NAMESPACE_URL, f"sim-pilot:product-evaluation:{case.id}"),
                status=TaskStatus.PENDING,
                specification=compilation.specification,
                created_at=now,
                updated_at=now,
            )
            runtime = RuntimeEngine()
            outcome = await runtime.run(
                task,
                ReferenceSimulationAdapter(),
                tracked_decisions,
                iteration_budget=configuration.max_runtime_iterations,
            )
            events = runtime.event_store.list_events(task.id)
            decisions = sum(
                event.event_type is RuntimeEventType.DECISION_GENERATED for event in events
            )
            selected_actions = tuple(
                action_type
                for event in events
                if event.event_type is RuntimeEventType.DECISION_GENERATED
                and isinstance((action := event.payload.get("action")), dict)
                and isinstance((action_type := action.get("type")), str)
            )
            executed = sum(event.event_type is RuntimeEventType.ACTION_EXECUTED for event in events)
            rejection_reasons = tuple(
                reason
                for event in events
                if event.event_type is RuntimeEventType.ACTION_REJECTED
                and isinstance((reason := event.payload.get("reason")), str)
            )
            runtime_result = EvaluationRuntimeResult(
                attempted=True,
                status=outcome.status.value,
                iterations=outcome.iterations,
                decisions=decisions,
                actions_selected=len(selected_actions),
                selected_actions=selected_actions,
                actions_executed=executed,
                actions_rejected=len(rejection_reasons),
                policy_rejections=sum(
                    not reason.startswith("adapter validation failed:")
                    for reason in rejection_reasons
                ),
                adapter_rejections=sum(
                    reason.startswith("adapter validation failed:") for reason in rejection_reasons
                ),
                intervention_required=outcome.status
                in {
                    TaskStatus.WAITING_FOR_APPROVAL,
                    TaskStatus.BLOCKED,
                    TaskStatus.FAILED,
                },
                reason=outcome.reason,
            )
    except Exception as error:  # noqa: BLE001 - every paid evaluation failure is evidence
        failure_category = error.__class__.__name__
        failure_message = _safe_error(error)

    calls = tuple(
        [
            _call("compiler", metadata, elapsed, configuration)
            for metadata, elapsed in tracked_compiler.calls
        ]
        + [
            _call("decision", metadata, elapsed, configuration)
            for metadata, elapsed in tracked_decisions.calls
        ]
    )
    latency, input_tokens, output_tokens, cost = _result_totals(calls)
    report = compilation.report if compilation is not None else None
    status = report.validation_status if report is not None else None
    return ProductEvaluationResult(
        case_id=case.id,
        category=case.category,
        instruction=case.instruction,
        adapter=case.adapter,
        expected_statuses=case.expected_statuses,
        expected_outcome_matched=status in case.expected_statuses,
        compilation_status=status,
        specification=(
            None
            if compilation is None or compilation.specification is None
            else compilation.specification.model_dump(mode="json")
        ),
        assumptions=() if report is None else report.assumptions,
        warnings=() if report is None else report.warnings,
        unsupported_requests=() if report is None else report.unsupported_requests,
        ambiguities=() if report is None else report.ambiguities,
        validation_errors=(
            ()
            if report is None
            else tuple(error.model_dump(mode="json") for error in report.validation_errors)
        ),
        semantic_validation_passed=report is not None and not report.validation_errors,
        runtime=runtime_result,
        calls=calls,
        compiler_call_count=tracked_compiler.attempts,
        decision_call_count=tracked_decisions.attempts,
        total_latency_ms=latency,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        estimated_cost_usd=cost,
        failure_category=failure_category,
        failure_message=failure_message,
    )


def _aggregate(results: tuple[ProductEvaluationResult, ...]) -> dict[str, object]:
    total = len(results)
    calls = tuple(call for result in results for call in result.calls)
    runtimes = tuple(result.runtime for result in results if result.runtime.attempted)
    statuses = Counter(
        result.compilation_status.value if result.compilation_status else "failed"
        for result in results
    )
    failures = Counter(
        result.failure_category for result in results if result.failure_category is not None
    )
    actions_selected = sum(runtime.actions_selected for runtime in runtimes)
    actions_rejected = sum(runtime.actions_rejected for runtime in runtimes)
    completed = tuple(
        runtime for runtime in runtimes if runtime.status == TaskStatus.COMPLETED.value
    )
    latencies = sorted(call.latency_ms for call in calls)
    ambiguous = tuple(result for result in results if result.category == "ambiguous")
    not_ambiguous = tuple(result for result in results if result.category != "ambiguous")
    unsupported_expected = tuple(
        result for result in results if ValidationStatus.UNSUPPORTED in result.expected_statuses
    )

    def percentile(percent: float) -> float:
        if not latencies:
            return 0.0
        index = min(round((len(latencies) - 1) * percent), len(latencies) - 1)
        return latencies[index]

    return {
        "schema_version": 1,
        "case_count": total,
        "completed_case_count": total,
        "provider_call_count": sum(
            result.compiler_call_count + result.decision_call_count for result in results
        ),
        "compiler_call_count": sum(result.compiler_call_count for result in results),
        "decision_call_count": sum(result.decision_call_count for result in results),
        "compilation_status_counts": dict(statuses),
        "expected_outcome_match_rate": (
            sum(result.expected_outcome_matched for result in results) / total if total else 0.0
        ),
        "valid_compilation_rate": statuses[ValidationStatus.VALID.value] / total if total else 0.0,
        "clarification_rate": (
            statuses[ValidationStatus.CLARIFICATION_REQUIRED.value] / total if total else 0.0
        ),
        "correct_clarification_rate": (
            sum(
                result.compilation_status is ValidationStatus.CLARIFICATION_REQUIRED
                for result in ambiguous
            )
            / len(ambiguous)
            if ambiguous
            else 0.0
        ),
        "false_clarification_rate": (
            sum(
                result.compilation_status is ValidationStatus.CLARIFICATION_REQUIRED
                for result in not_ambiguous
            )
            / len(not_ambiguous)
            if not_ambiguous
            else 0.0
        ),
        "unsupported_rate": (
            statuses[ValidationStatus.UNSUPPORTED.value] / total if total else 0.0
        ),
        "unsupported_classification_accuracy": (
            sum(
                result.compilation_status is ValidationStatus.UNSUPPORTED
                for result in unsupported_expected
            )
            / len(unsupported_expected)
            if unsupported_expected
            else 0.0
        ),
        "runtime_attempt_count": len(runtimes),
        "runtime_completion_rate": (len(completed) / len(runtimes) if runtimes else 0.0),
        "average_model_calls_per_completed_task": (
            sum(result.compiler_call_count + result.decision_call_count for result in results)
            / len(completed)
            if completed
            else 0.0
        ),
        "intervention_rate": (
            sum(runtime.intervention_required for runtime in runtimes) / len(runtimes)
            if runtimes
            else 0.0
        ),
        "action_rejection_rate": (actions_rejected / actions_selected if actions_selected else 0.0),
        "validation_intervention_rate": (
            sum(runtime.actions_rejected > 0 for runtime in runtimes) / len(runtimes)
            if runtimes
            else 0.0
        ),
        "average_call_latency_ms": (
            sum(call.latency_ms for call in calls) / len(calls) if calls else 0.0
        ),
        "median_call_latency_ms": percentile(0.5),
        "p95_call_latency_ms": percentile(0.95),
        "input_tokens": sum(result.total_input_tokens for result in results),
        "output_tokens": sum(result.total_output_tokens for result in results),
        "estimated_cost_usd": sum(result.estimated_cost_usd for result in results),
        "average_estimated_cost_usd": (
            sum(result.estimated_cost_usd for result in results) / total if total else 0.0
        ),
        "failure_categories": dict(failures),
    }


def _write_review_file(
    path: Path,
    results: tuple[ProductEvaluationResult, ...],
) -> None:
    existing: dict[str, dict[str, object]] = {}
    if path.exists():
        raw = TypeAdapter(list[dict[str, object]]).validate_json(path.read_text(encoding="utf-8"))
        existing = {
            case_id: item for item in raw if isinstance((case_id := item.get("case_id")), str)
        }
    rows: list[dict[str, object]] = []
    for result in results:
        prior = existing.get(result.case_id, {})
        row: dict[str, object] = result.model_dump(mode="json")
        row["manual_rating"] = prior.get("manual_rating")
        row["reviewer_notes"] = prior.get("reviewer_notes")
        rows.append(row)
    _atomic_write(path, json.dumps(rows, indent=2, default=str) + "\n")


async def run_product_evaluation(
    *,
    fixture_path: Path,
    output_directory: Path,
    compiler_provider_factory: Callable[[ProductEvaluationCase], CompilerProvider],
    decision_provider_factory: Callable[[ProductEvaluationCase], DecisionProvider],
    configuration: EvaluationRunConfiguration,
    force: bool = False,
    case_ids: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Run selected cases and preserve one atomic result per case for resume."""
    cases = load_evaluation_cases(fixture_path)
    if case_ids:
        unknown = case_ids - {case.id for case in cases}
        if unknown:
            raise ValueError(f"unknown evaluation case ids: {', '.join(sorted(unknown))}")
        cases = tuple(case for case in cases if case.id in case_ids)
    _secure_directory(output_directory)
    results_directory = output_directory / "results"
    _secure_directory(results_directory)
    fixture_digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    manifest = {
        **configuration.model_dump(mode="json"),
        "fixture": str(fixture_path),
        "fixture_sha256": fixture_digest,
        "selected_case_ids": [case.id for case in cases],
        "maximum_provider_calls": len(cases)
        + sum(configuration.max_runtime_iterations for case in cases if case.run_runtime),
        "recording_notice": (
            "Contains prompts, instructions, structured responses, and telemetry; "
            "contains no API keys."
        ),
    }
    _atomic_write(output_directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")

    results: list[ProductEvaluationResult] = []
    for case in cases:
        destination = results_directory / f"{case.id}.json"
        if destination.exists() and not force:
            results.append(ProductEvaluationResult.model_validate_json(destination.read_text()))
            continue
        result = await _evaluate_case(
            case,
            compiler_provider_factory(case),
            decision_provider_factory(case),
            configuration,
        )
        _atomic_write(destination, result.model_dump_json(indent=2) + "\n")
        results.append(result)

    materialized = tuple(results)
    aggregate = _aggregate(materialized)
    _atomic_write(output_directory / "aggregate.json", json.dumps(aggregate, indent=2) + "\n")
    _write_review_file(output_directory / "manual_review.json", materialized)
    return aggregate
