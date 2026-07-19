"""Recorded three-pass founder intelligence evaluation over approved snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.compiler import AnalysisCompilation, AnalysisCompiler
from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ExplanationClaimType,
)
from sim_pilot.analysis.evaluation import FounderIntelligenceCase
from sim_pilot.analysis.explanation import (
    ExplanationProvider,
    ExplanationStyle,
    explanation_input,
    validate_explanation,
)
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text
from sim_pilot.provider_metadata import ProviderMetadata


class FounderPass(StrEnum):
    DETERMINISTIC = "deterministic"
    CODEX_COMPILER = "codex_compiler"
    CODEX_EXPLANATION = "codex_explanation"


class FounderCaseChecks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    analysis_type_expected: bool | None = None
    status_expected: bool | None = None
    evidence_types_present: bool | None = None
    explanation_faithful: bool | None = None


class FounderSessionCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    pass_name: FounderPass
    case_id: str
    question: str
    compilation: AnalysisCompilation | None = None
    response: AnalysisResponse | None = None
    rendered_answer: str | None = None
    checks: FounderCaseChecks
    latency_ms: float = Field(ge=0)
    provider_metadata: ProviderMetadata | None = None
    error: str | None = None


class FounderReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    case_id: str
    question: str
    answer: str
    manual_rating: Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"] | None = None
    revealed_nonobvious_information: Literal["yes", "partially", "no"] | None = None
    would_use_during_gameplay: Literal["yes", "maybe", "no"] | None = None
    identified_right_subject: bool | None = None
    most_important_finding_first: bool | None = None
    evidence_sufficient: bool | None = None
    limitation_understandable: bool | None = None
    too_verbose: bool | None = None
    faster_than_manual_inspection: bool | None = None
    next_question: str | None = None
    reviewer_notes: str | None = None


class FounderSessionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    started_at: datetime
    completed_at: datetime
    current_snapshot_id: str
    comparison_snapshot_id: str
    world_id: str
    company_id: str
    company_name: str
    capability_fingerprint: str
    save_generation: int
    snapshot_complete: bool
    case_count: int
    deterministic_case_count: int
    compiler_case_count: int
    explanation_case_count: int
    codex_invocations: int
    write_flags_enabled: Literal[False] = False


def run_founder_session(
    *,
    cases: tuple[FounderIntelligenceCase, ...],
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    compiler: AnalysisCompiler,
    explanation_provider: ExplanationProvider,
    compiler_metadata: Callable[[], ProviderMetadata | None],
    explanation_metadata: Callable[[], ProviderMetadata | None],
    output_directory: Path,
    explanation_case_ids: frozenset[str],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FounderSessionManifest:
    """Run the approved 37/45/5 pass structure without mutating gameplay."""
    started_at = clock()
    _validate_snapshots(current, comparison)
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write_private_text(
        output_directory / "current-snapshot.json", current.model_dump_json(indent=2)
    )
    atomic_write_private_text(
        output_directory / "comparison-snapshot.json", comparison.model_dump_json(indent=2)
    )

    service = AnalysisService(default_analyzer_registry())
    supported = tuple(case for case in cases if _is_supported(case))
    deterministic_results = tuple(
        _run_deterministic(case, current, comparison, service) for case in supported
    )
    _write_results(output_directory / "pass-a-deterministic.json", deterministic_results)

    compiler_results: list[FounderSessionCaseResult] = []
    compiled_responses: dict[str, AnalysisResponse] = {}
    for case in cases:
        result = _run_compiler_case(
            case,
            current,
            comparison,
            service,
            compiler,
            compiler_metadata,
        )
        compiler_results.append(result)
        if result.response is not None:
            compiled_responses[case.case_id] = result.response
    _write_results(output_directory / "pass-b-codex-compiler.json", tuple(compiler_results))

    explanation_results: list[FounderSessionCaseResult] = []
    for case in cases:
        if case.case_id not in explanation_case_ids:
            continue
        response = compiled_responses.get(case.case_id)
        explanation_results.append(
            _run_explanation_case(
                case,
                response,
                current,
                explanation_provider,
                explanation_metadata,
            )
        )
    _write_results(output_directory / "pass-c-codex-explanation.json", tuple(explanation_results))

    preferred = {item.case_id: item for item in compiler_results if item.response is not None}
    review = tuple(
        FounderReviewItem(
            case_id=case.case_id,
            question=case.question,
            answer=(
                preferred.get(case.case_id) or deterministic_results[supported.index(case)]
            ).rendered_answer
            or "No rendered answer was produced.",
        )
        for case in supported
    )
    atomic_write_private_text(
        output_directory / "manual-review.json",
        "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in review) + "\n]",
    )

    company = next(
        item for item in current.companies if item.id == current.metadata.observer_company_id
    )
    manifest = FounderSessionManifest(
        started_at=started_at,
        completed_at=clock(),
        current_snapshot_id=current.metadata.snapshot_id,
        comparison_snapshot_id=comparison.metadata.snapshot_id,
        world_id=current.metadata.world_id,
        company_id=company.id,
        company_name=company.name,
        capability_fingerprint=current.metadata.capability_fingerprint,
        save_generation=current.metadata.save_generation,
        snapshot_complete=current.metadata.complete,
        case_count=len(cases),
        deterministic_case_count=len(deterministic_results),
        compiler_case_count=len(compiler_results),
        explanation_case_count=len(explanation_results),
        codex_invocations=len(compiler_results)
        + sum(item.provider_metadata is not None for item in explanation_results),
    )
    atomic_write_private_text(
        output_directory / "manifest.json", manifest.model_dump_json(indent=2)
    )
    return manifest


def _run_deterministic(
    case: FounderIntelligenceCase,
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    service: AnalysisService,
) -> FounderSessionCaseResult:
    started = perf_counter()
    try:
        request = AnalysisRequest(
            analysis_type=case.expected_analysis_types[0],
            question=case.question,
            comparison_snapshot_id=(
                comparison.metadata.snapshot_id if case.requires_comparison else None
            ),
        )
        response = service.analyze(
            request, current, comparison if case.requires_comparison else None
        )
        return _result(
            FounderPass.DETERMINISTIC,
            case,
            started,
            response=response,
            current=current,
        )
    except Exception as error:
        return _result(FounderPass.DETERMINISTIC, case, started, error=str(error))


def _run_compiler_case(
    case: FounderIntelligenceCase,
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    service: AnalysisService,
    compiler: AnalysisCompiler,
    metadata: Callable[[], ProviderMetadata | None],
) -> FounderSessionCaseResult:
    import asyncio

    started = perf_counter()
    try:
        compilation = asyncio.run(compiler.compile(case.question))
        response: AnalysisResponse | None = None
        if compilation.request is not None:
            request = compilation.request.model_copy(
                update={
                    "comparison_snapshot_id": (
                        comparison.metadata.snapshot_id if case.requires_comparison else None
                    )
                }
            )
            response = service.analyze(
                request, current, comparison if case.requires_comparison else None
            )
        return _result(
            FounderPass.CODEX_COMPILER,
            case,
            started,
            compilation=compilation,
            response=response,
            current=current,
            provider_metadata=metadata(),
        )
    except Exception as error:
        return _result(
            FounderPass.CODEX_COMPILER,
            case,
            started,
            provider_metadata=metadata(),
            error=str(error),
        )


def _run_explanation_case(
    case: FounderIntelligenceCase,
    response: AnalysisResponse | None,
    current: WorldSnapshot,
    provider: ExplanationProvider,
    metadata: Callable[[], ProviderMetadata | None],
) -> FounderSessionCaseResult:
    import asyncio

    started = perf_counter()
    if response is None:
        return _result(
            FounderPass.CODEX_EXPLANATION,
            case,
            started,
            error="Pass B did not produce an analyzable response.",
        )
    try:
        explanation = asyncio.run(
            provider.explain(explanation_input(response, style=ExplanationStyle.COMPACT))
        )
        validated = validate_explanation(explanation, response)
        explained = response.model_copy(update={"explanation": validated})
        return _result(
            FounderPass.CODEX_EXPLANATION,
            case,
            started,
            response=explained,
            current=current,
            provider_metadata=metadata(),
            explanation_faithful=all(
                item.claim_type in set(ExplanationClaimType) for item in validated.statements
            ),
        )
    except Exception as error:
        return _result(
            FounderPass.CODEX_EXPLANATION,
            case,
            started,
            response=response,
            current=current,
            provider_metadata=metadata(),
            explanation_faithful=False,
            error=str(error),
        )


def _result(
    pass_name: FounderPass,
    case: FounderIntelligenceCase,
    started: float,
    *,
    compilation: AnalysisCompilation | None = None,
    response: AnalysisResponse | None = None,
    current: WorldSnapshot | None = None,
    provider_metadata: ProviderMetadata | None = None,
    explanation_faithful: bool | None = None,
    error: str | None = None,
) -> FounderSessionCaseResult:
    evidence_types = (
        None
        if response is None
        else set(case.required_evidence_types).issubset(
            {
                evidence.entity_type
                for finding in response.findings
                for evidence in finding.evidence
                if evidence.entity_type is not None
            }
        )
    )
    analysis_type = None
    if response is not None:
        analysis_type = response.request.analysis_type in case.expected_analysis_types
    elif compilation is not None and compilation.request is not None:
        analysis_type = compilation.request.analysis_type in case.expected_analysis_types
    status = _observed_status(compilation, response)
    return FounderSessionCaseResult(
        pass_name=pass_name,
        case_id=case.case_id,
        question=case.question,
        compilation=compilation,
        response=response,
        rendered_answer=(
            None
            if response is None or current is None
            else render_analysis(response, snapshot=current)
        ),
        checks=FounderCaseChecks(
            analysis_type_expected=analysis_type,
            status_expected=None if status is None else status in case.expected_statuses,
            evidence_types_present=evidence_types,
            explanation_faithful=explanation_faithful,
        ),
        latency_ms=(perf_counter() - started) * 1_000,
        provider_metadata=provider_metadata,
        error=error,
    )


def _observed_status(
    compilation: AnalysisCompilation | None, response: AnalysisResponse | None
) -> AnalysisStatus | None:
    if response is not None:
        return response.status
    if compilation is None:
        return None
    if compilation.clarification is not None:
        return AnalysisStatus.CLARIFICATION_REQUIRED
    if compilation.unsupported_reason is not None:
        return AnalysisStatus.UNSUPPORTED
    return None


def _is_supported(case: FounderIntelligenceCase) -> bool:
    return bool(
        {AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_LIMITATIONS}
        & set(case.expected_statuses)
    )


def _validate_snapshots(current: WorldSnapshot, comparison: WorldSnapshot) -> None:
    if not current.metadata.complete or not comparison.metadata.complete:
        raise ValueError("founder session requires complete snapshots")
    if current.metadata.world_id != comparison.metadata.world_id:
        raise ValueError("founder session snapshots must share a world identity")
    if current.metadata.capability_fingerprint != comparison.metadata.capability_fingerprint:
        raise ValueError("founder session snapshots must share a capability fingerprint")


def _write_results(path: Path, results: tuple[FounderSessionCaseResult, ...]) -> None:
    atomic_write_private_text(
        path,
        "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in results) + "\n]",
    )
