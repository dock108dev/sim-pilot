from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sim_pilot.analysis import (
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    EvidenceReference,
    EvidenceSourceType,
    FindingKind,
    FindingSeverity,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)


def request() -> AnalysisRequest:
    return AnalysisRequest(
        analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
        question="Which trains made the least money last year?",
        filters=(
            AnalysisFilter(
                field=AnalysisFilterField.VEHICLE_TYPE,
                operator=AnalysisFilterOperator.EQUAL,
                values=("rail",),
            ),
        ),
        ranking=RankingRequest(
            metric=RankingMetric.PROFIT_LAST_YEAR,
            direction=RankingDirection.ASCENDING,
        ),
    )


def test_analysis_request_is_semantic_strict_and_immutable() -> None:
    value = request()
    assert value.analysis_type is AnalysisType.VEHICLE_PERFORMANCE
    assert value.maximum_findings == 5
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate({**value.model_dump(), "unknown": True}, strict=True)
    with pytest.raises(ValidationError):
        value.question = "changed"  # type: ignore[misc]


def test_request_rejects_ambiguous_subject_and_filter_arity() -> None:
    with pytest.raises(ValidationError, match="requires subject IDs"):
        AnalysisRequest(
            analysis_type=AnalysisType.ENTITY_SUMMARY,
            question="Summarize it.",
            subject_type=AnalysisSubjectType.VEHICLE,
        )
    with pytest.raises(ValidationError, match="requires exactly one"):
        AnalysisFilter(
            field=AnalysisFilterField.AGE_DAYS,
            operator=AnalysisFilterOperator.GREATER_THAN,
            values=(10, 20),
        )


def test_findings_recommendations_and_response_keep_authority_separate() -> None:
    evidence = EvidenceReference(
        source_type=EvidenceSourceType.SNAPSHOT_FIELD,
        snapshot_id="snapshot-1",
        entity_type=AnalysisSubjectType.VEHICLE,
        entity_id="vehicle:opaque",
        field="profit_last_year",
        observed_value=-100,
    )
    finding = AnalysisFinding(
        finding_id="finding-1",
        finding_code="negative_last_year_profit",
        analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
        kind=FindingKind.OBSERVED_FACT,
        severity=FindingSeverity.WARNING,
        title="Negative last-year profit",
        summary="One observed vehicle lost money last year.",
        metric_name="profit_last_year",
        metric_value=-100,
        confidence=EvidenceConfidence.HIGH,
        evidence=(evidence,),
        recommendation_ids=("recommendation-1",),
    )
    recommendation = AnalysisRecommendation(
        recommendation_id="recommendation-1",
        title="Inspect the vehicle",
        rationale="Its observed last-year profit is negative.",
        priority=1,
        affected_entity_ids=("vehicle:opaque",),
        supporting_finding_ids=(finding.finding_id,),
    )
    response = AnalysisResponse(
        request=request(),
        snapshot_id="snapshot-1",
        status=AnalysisStatus.COMPLETED,
        answer="One rail vehicle has negative last-year profit.",
        findings=(finding,),
        recommendations=(recommendation,),
        generated_at=datetime.now(UTC),
    )

    assert response.recommendations[0].executable is False
    assert AnalysisResponse.model_validate_json(response.model_dump_json()) == response


def test_evidence_does_not_conflate_bridge_and_observation_sequences() -> None:
    assert "observation_sequence" not in EvidenceReference.model_fields
    with pytest.raises(ValidationError, match="comparison_value requires"):
        EvidenceReference(
            source_type=EvidenceSourceType.DERIVED_METRIC,
            snapshot_id="snapshot-1",
            field="debt_to_cash",
            observed_value=2.0,
            comparison_value=1.0,
        )
