"""Bounded, opt-in product proving runner for hosted compiler and decision providers."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, perf_counter
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
from sim_pilot.intent_compiler.prompt import capability_catalog
from sim_pilot.private_files import atomic_write_private_text, ensure_private_directory
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
ManualRating = Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"]


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
    estimated_cost_usd: float | None = Field(default=None, ge=0)


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
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    failure_category: str | None = None
    failure_message: str | None = None
    compiler_rating: ManualRating | None = None
    decision_rating: ManualRating | None = None
    runtime_rating: ManualRating | None = None
    overall_rating: ManualRating | None = None
    reviewer_notes: str | None = None


class EvaluationRunConfiguration(EvaluationModel):
    compiler_provider: Literal["openai", "codex"]
    decision_provider: Literal["openai", "codex"]
    compiler_model: str = Field(min_length=1)
    decision_model: str = Field(min_length=1)
    input_cost_per_million_usd: float = Field(ge=0)
    output_cost_per_million_usd: float = Field(ge=0)
    max_runtime_iterations: int = Field(gt=0)
    max_output_tokens_per_call: int | None = Field(default=None, gt=0)
    cost_reporting: Literal["api_estimate", "plan_allowance"] = "api_estimate"
    max_compiler_calls: int = Field(default=31, gt=0)
    max_decision_calls: int = Field(default=48, ge=0)
    max_total_calls: int = Field(default=79, gt=0)
    total_wall_clock_seconds: float = Field(default=3_600, gt=0)
    stop_on_usage_limit: bool = True


class EvaluationLimitError(RuntimeError):
    """The explicitly configured evaluation invocation budget was reached."""


class _EvaluationBudget:
    def __init__(self, configuration: EvaluationRunConfiguration) -> None:
        self._configuration = configuration
        self._started = monotonic()
        self.compiler_calls = 0
        self.decision_calls = 0

    def before_compiler(self) -> None:
        self._check_time()
        if self.compiler_calls >= self._configuration.max_compiler_calls:
            raise EvaluationLimitError("maximum compiler-call count reached")
        self._check_total()
        self.compiler_calls += 1

    def before_decision(self) -> None:
        self._check_time()
        if self.decision_calls >= self._configuration.max_decision_calls:
            raise EvaluationLimitError("maximum decision-call count reached")
        self._check_total()
        self.decision_calls += 1

    def _check_total(self) -> None:
        if self.compiler_calls + self.decision_calls >= self._configuration.max_total_calls:
            raise EvaluationLimitError("maximum total provider-call count reached")

    def _check_time(self) -> None:
        if monotonic() - self._started >= self._configuration.total_wall_clock_seconds:
            raise EvaluationLimitError("total evaluation wall-clock limit reached")


class _TrackingCompilerProvider:
    def __init__(self, provider: CompilerProvider, budget: _EvaluationBudget) -> None:
        self._provider = provider
        self._budget = budget
        self.calls: list[tuple[ProviderMetadata, float]] = []
        self.attempts = 0

    async def compile(self, instruction: str) -> CompilerProviderResult:
        self._budget.before_compiler()
        self.attempts += 1
        started = perf_counter()
        result = await self._provider.compile(instruction)
        elapsed = (perf_counter() - started) * 1000
        self.calls.append((result.metadata, elapsed))
        return result


class _TrackingDecisionProvider:
    def __init__(self, provider: DecisionProvider, budget: _EvaluationBudget) -> None:
        self._provider = provider
        self._budget = budget
        self.calls: list[tuple[ProviderMetadata, float]] = []
        self.attempts = 0

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        self._budget.before_decision()
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
    return capability_catalog(case.adapter)


def _estimated_cost(
    usage: ProviderTokenUsage | None,
    configuration: EvaluationRunConfiguration,
) -> float | None:
    if configuration.cost_reporting == "plan_allowance" or usage is None:
        return None
    return (
        usage.input_tokens * configuration.input_cost_per_million_usd
        + usage.output_tokens * configuration.output_cost_per_million_usd
    ) / 1_000_000


def _provider_surface(configuration: EvaluationRunConfiguration) -> str:
    providers = {configuration.compiler_provider, configuration.decision_provider}
    if providers == {"codex"}:
        return "Codex CLI using authenticated ChatGPT access"
    if providers == {"openai"}:
        return "OpenAI API"
    return "Mixed: OpenAI API and Codex CLI using authenticated ChatGPT access"


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


def _result_totals(calls: Iterable[EvaluationCall]) -> tuple[float, int, int, float | None]:
    materialized = tuple(calls)
    return (
        sum(item.latency_ms for item in materialized),
        sum(item.token_usage.input_tokens for item in materialized if item.token_usage),
        sum(item.token_usage.output_tokens for item in materialized if item.token_usage),
        (
            None
            if any(item.estimated_cost_usd is None for item in materialized)
            else sum(item.estimated_cost_usd or 0 for item in materialized)
        ),
    )


async def _evaluate_case(
    case: ProductEvaluationCase,
    compiler_provider: CompilerProvider,
    decision_provider: DecisionProvider,
    configuration: EvaluationRunConfiguration,
    budget: _EvaluationBudget,
) -> ProductEvaluationResult:
    tracked_compiler = _TrackingCompilerProvider(compiler_provider, budget)
    tracked_decisions = _TrackingDecisionProvider(decision_provider, budget)
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
    if configuration.cost_reporting == "plan_allowance":
        cost = None
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


def _aggregate(
    results: tuple[ProductEvaluationResult, ...],
    configuration: EvaluationRunConfiguration,
) -> dict[str, object]:
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
    costs = tuple(
        result.estimated_cost_usd for result in results if result.estimated_cost_usd is not None
    )
    cost_available = len(costs) == len(results)

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
        "provider_surface": _provider_surface(configuration),
        "direct_api_cost": (
            "none; Codex allowance or credit usage is subject to the authenticated plan"
            if configuration.cost_reporting == "plan_allowance"
            else "estimated from token telemetry"
        ),
        "estimated_cost_usd": sum(costs) if cost_available else None,
        "average_estimated_cost_usd": (sum(costs) / total if total and cost_available else None),
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
        legacy_rating = prior.pop("manual_rating", None)
        row["compiler_rating"] = prior.get("compiler_rating")
        row["decision_rating"] = prior.get("decision_rating")
        row["runtime_rating"] = prior.get("runtime_rating")
        row["overall_rating"] = prior.get("overall_rating", legacy_rating)
        if row["overall_rating"] is None and legacy_rating is not None:
            row["overall_rating"] = legacy_rating
        row["reviewer_notes"] = prior.get("reviewer_notes")
        rows.append(row)
    atomic_write_private_text(path, json.dumps(rows, indent=2, default=str) + "\n")


def _load_evaluation_result(path: Path) -> ProductEvaluationResult:
    """Load a result while migrating the pre-SSOT aggregate rating at the file boundary."""
    raw = TypeAdapter(dict[str, object]).validate_json(path.read_text(encoding="utf-8"))
    legacy_rating = raw.pop("manual_rating", None)
    if raw.get("overall_rating") is None and legacy_rating is not None:
        raw["overall_rating"] = legacy_rating
    return ProductEvaluationResult.model_validate_json(json.dumps(raw))


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
    maximum_required_compiler_calls = len(cases)
    maximum_required_decision_calls = sum(
        configuration.max_runtime_iterations for case in cases if case.run_runtime
    )
    if maximum_required_compiler_calls > configuration.max_compiler_calls:
        raise ValueError("selected cases exceed the configured compiler-call limit")
    if maximum_required_decision_calls > configuration.max_decision_calls:
        raise ValueError("selected cases exceed the configured decision-call limit")
    if (
        maximum_required_compiler_calls + maximum_required_decision_calls
        > configuration.max_total_calls
    ):
        raise ValueError("selected cases exceed the configured total provider-call limit")
    budget = _EvaluationBudget(configuration)
    ensure_private_directory(output_directory)
    results_directory = output_directory / "results"
    ensure_private_directory(results_directory)
    fixture_digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    manifest = {
        **configuration.model_dump(mode="json"),
        "fixture": str(fixture_path),
        "fixture_sha256": fixture_digest,
        "selected_case_ids": [case.id for case in cases],
        "maximum_provider_calls": maximum_required_compiler_calls + maximum_required_decision_calls,
        "provider_surface": _provider_surface(configuration),
        "recording_notice": (
            "Contains prompts, instructions, structured responses, and telemetry; "
            "contains no API keys."
        ),
    }
    atomic_write_private_text(
        output_directory / "manifest.json", json.dumps(manifest, indent=2) + "\n"
    )

    results: list[ProductEvaluationResult] = []
    for case in cases:
        destination = results_directory / f"{case.id}.json"
        if destination.exists() and not force:
            persisted_result = _load_evaluation_result(destination)
            atomic_write_private_text(
                destination, persisted_result.model_dump_json(indent=2) + "\n"
            )
            results.append(persisted_result)
            continue
        result = await _evaluate_case(
            case,
            compiler_provider_factory(case),
            decision_provider_factory(case),
            configuration,
            budget,
        )
        atomic_write_private_text(destination, result.model_dump_json(indent=2) + "\n")
        results.append(result)
        if (
            configuration.stop_on_usage_limit
            and result.failure_category is not None
            and (
                "UsageLimit" in result.failure_category
                or "usage or credit limit" in (result.failure_message or "")
            )
        ):
            break

    materialized = tuple(results)
    aggregate = _aggregate(materialized, configuration)
    atomic_write_private_text(
        output_directory / "aggregate.json", json.dumps(aggregate, indent=2) + "\n"
    )
    _write_review_file(output_directory / "manual_review.json", materialized)
    return aggregate
