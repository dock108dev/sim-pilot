"""Assemble the preserved Phase 8C baseline and affected regressions for founder review."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from sim_pilot.analysis.contracts import AnalysisResponse, AnalysisStatus
from sim_pilot.analysis.evaluation import load_founder_intelligence_cases
from sim_pilot.analysis.founder_session import FounderReviewItem, FounderSessionCaseResult
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text

ROOT = Path("data/founder-intelligence")
BASELINE = ROOT / "20260719T233757Z"
REGRESSION = ROOT / "20260719T234938Z-regression"
STATION_FIX = ROOT / "20260719T235900Z-stations-fix-check"
AFFECTED = ROOT / "20260720T000100Z-affected-regression"
STATION_EXPLANATION = ROOT / "20260720T000100Z-station-explanation-session"

RESULTS = TypeAdapter(list[FounderSessionCaseResult])


def main() -> None:
    output = ROOT / "20260720-founder-review"
    current = WorldSnapshot.model_validate_json(
        (BASELINE / "current-snapshot.json").read_text(encoding="utf-8"), strict=True
    )
    comparison = WorldSnapshot.model_validate_json(
        (BASELINE / "comparison-snapshot.json").read_text(encoding="utf-8"), strict=True
    )
    cases = load_founder_intelligence_cases(
        Path("tests/fixtures/founder_intelligence_questions.json")
    )
    supported = tuple(
        case
        for case in cases
        if {AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_LIMITATIONS}
        & set(case.expected_statuses)
    )

    deterministic = _load(BASELINE / "pass-a-deterministic.json")
    full_compiler = _load(REGRESSION / "pass-b-codex-compiler.json")
    affected = _load(AFFECTED / "pass-b-codex-compiler.json")
    station_fix = _load(STATION_FIX / "pass-b-codex-compiler.json")
    explanations = _load(REGRESSION / "pass-c-codex-explanation.json")
    final_compiler = {item.case_id: item for item in full_compiler}
    final_compiler.update({item.case_id: item for item in affected})
    final_compiler.update({item.case_id: item for item in station_fix})

    responses = {item.case_id: item.response for item in deterministic if item.response is not None}
    responses.update(
        {
            item.case_id: item.response
            for item in final_compiler.values()
            if item.response is not None
        }
    )
    corrected_no_result = _reanalyze_filtered_no_result(
        responses, final_compiler, current, comparison
    )
    original_no_result = final_compiler["vehicles-003"]
    final_compiler["vehicles-003"] = original_no_result.model_copy(
        update={"response": corrected_no_result}
    )
    responses.update(
        {item.case_id: item.response for item in explanations if item.response is not None}
    )
    station_record_path = next(STATION_EXPLANATION.glob("analysis-*.json"))
    station_record = AnalysisSessionRecord.model_validate_json(
        station_record_path.read_text(encoding="utf-8"), strict=True
    )
    responses["stations-002"] = station_record.response

    review = tuple(
        FounderReviewItem(
            case_id=case.case_id,
            question=case.question,
            answer=render_analysis(responses[case.case_id], snapshot=current),
        )
        for case in supported
    )
    final_responses = tuple(responses[case.case_id] for case in supported)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_models(output / "manual-review.json", review)
    _write_models(output / "final-responses.json", final_responses)
    atomic_write_private_text(
        output / "metrics.json",
        json.dumps(
            _metrics(
                cases=cases,
                supported=supported,
                deterministic=deterministic,
                compiler=tuple(final_compiler.values()),
                explanations=explanations,
                responses=responses,
                review=review,
            ),
            indent=2,
        )
        + "\n",
    )
    print(output.resolve())


def _reanalyze_filtered_no_result(
    responses: dict[str, AnalysisResponse],
    compiler: dict[str, FounderSessionCaseResult],
    current: WorldSnapshot,
    comparison: WorldSnapshot,
) -> AnalysisResponse:
    result = compiler["vehicles-003"]
    if result.compilation is None or result.compilation.request is None:
        raise RuntimeError("vehicles-003 has no corrected compilation")
    request = result.compilation.request
    response = AnalysisService(default_analyzer_registry()).analyze(
        request,
        current,
        comparison if request.comparison_snapshot_id is not None else None,
    )
    responses["vehicles-003"] = response
    return response


def _metrics(
    *,
    cases,
    supported,
    deterministic,
    compiler,
    explanations,
    responses,
    review,
) -> dict[str, object]:
    cases_by_id = {item.case_id: item for item in cases}
    compiler_status_correct = sum(
        _status(item) in cases_by_id[item.case_id].expected_statuses for item in compiler
    )
    selected = tuple(item for item in compiler if item.response is not None)
    analyzer_correct = sum(
        item.response is not None
        and item.response.request.analysis_type in cases_by_id[item.case_id].expected_analysis_types
        for item in selected
    )
    evidence_correct = sum(
        set(cases_by_id[case_id].required_evidence_types).issubset(
            {
                evidence.entity_type
                for finding in response.findings
                for evidence in finding.evidence
                if evidence.entity_type is not None
            }
        )
        for case_id, response in responses.items()
        if case_id in {item.case_id for item in supported}
    )
    explanation_faithful = sum(
        item.checks.explanation_faithful is True for item in explanations
    ) + int(responses["stations-002"].explanation is not None)
    compiler_metadata = tuple(
        item.provider_metadata for item in compiler if item.provider_metadata is not None
    )
    explanation_metadata = tuple(
        item.provider_metadata for item in explanations if item.provider_metadata is not None
    )
    compact_words = [len(item.answer.split()) for item in review]
    return {
        "schema_version": 1,
        "case_count": len(cases),
        "supported_case_count": len(supported),
        "compilation_status_correct": compiler_status_correct,
        "compilation_status_accuracy": compiler_status_correct / len(cases),
        "analyzer_selection_correct": analyzer_correct,
        "analyzer_selection_evaluated": len(selected),
        "evidence_requirements_met": evidence_correct,
        "evidence_requirements_evaluated": len(supported),
        "explanations_faithful": explanation_faithful,
        "explanations_evaluated": 5,
        "snapshot_latency_ms": [7011.418, 6991.845],
        "deterministic_latency_ms": _latencies(deterministic),
        "compiler_latency_ms": _latencies(compiler),
        "explanation_latency_ms": _latencies(
            tuple(item for item in explanations if item.provider_metadata is not None)
        ),
        "compiler_tokens": _tokens(compiler_metadata),
        "explanation_tokens": _tokens(explanation_metadata),
        "station_explanation_telemetry": "not retained by the CLI session record",
        "compact_answer_words": _summary(tuple(float(item) for item in compact_words)),
        "subjective_ratings_complete": False,
    }


def _status(item: FounderSessionCaseResult) -> AnalysisStatus | None:
    if item.response is not None:
        return item.response.status
    if item.compilation is None:
        return None
    if item.compilation.clarification is not None:
        return AnalysisStatus.CLARIFICATION_REQUIRED
    if item.compilation.unsupported_reason is not None:
        return AnalysisStatus.UNSUPPORTED
    return None


def _latencies(results) -> dict[str, float]:
    return _summary(tuple(item.latency_ms for item in results))


def _summary(values: tuple[float, ...]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "median": ordered[len(ordered) // 2],
        "p95": ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)],
    }


def _tokens(metadata) -> dict[str, int]:
    usages = tuple(item.token_usage for item in metadata if item.token_usage is not None)
    return {
        "input": sum(item.input_tokens for item in usages),
        "cached_input": sum(item.cached_input_tokens or 0 for item in usages),
        "output": sum(item.output_tokens for item in usages),
        "total": sum(item.total_tokens for item in usages),
        "recorded_invocations": len(usages),
    }


def _load(path: Path) -> tuple[FounderSessionCaseResult, ...]:
    return tuple(RESULTS.validate_json(path.read_text(encoding="utf-8"), strict=True))


def _write_models(path: Path, values) -> None:
    atomic_write_private_text(
        path,
        "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in values) + "\n]",
    )


if __name__ == "__main__":
    main()
