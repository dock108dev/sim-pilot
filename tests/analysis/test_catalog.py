import pytest

from sim_pilot.analysis.catalog import validate_analysis_request
from sim_pilot.analysis.contracts import (
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisRequest,
    AnalysisSubjectType,
    AnalysisType,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)
from sim_pilot.analysis.errors import AnalysisRequestError


def test_catalog_accepts_supported_vehicle_filter_and_ranking() -> None:
    request = AnalysisRequest(
        analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
        question="Which trains performed worst?",
        subject_type=AnalysisSubjectType.COMPANY,
        subject_ids=("company-1",),
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

    capability = validate_analysis_request(request)

    assert capability.analysis_type is AnalysisType.VEHICLE_PERFORMANCE


def test_catalog_rejects_unsupported_metric_filter_and_missing_comparison() -> None:
    with pytest.raises(AnalysisRequestError, match="ranking metric"):
        validate_analysis_request(
            AnalysisRequest(
                analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
                question="Rank by population.",
                ranking=RankingRequest(
                    metric=RankingMetric.POPULATION,
                    direction=RankingDirection.DESCENDING,
                ),
            )
        )
    with pytest.raises(AnalysisRequestError, match="unsupported filters"):
        validate_analysis_request(
            AnalysisRequest(
                analysis_type=AnalysisType.FINANCIAL_SUMMARY,
                question="Filter company finances by route.",
                filters=(
                    AnalysisFilter(
                        field=AnalysisFilterField.ROUTE_ID,
                        operator=AnalysisFilterOperator.EQUAL,
                        values=("route-1",),
                    ),
                ),
            )
        )
    with pytest.raises(AnalysisRequestError, match="requires a comparison"):
        validate_analysis_request(
            AnalysisRequest(
                analysis_type=AnalysisType.ANOMALY_DETECTION,
                question="What changed unusually?",
            )
        )


def test_entity_summary_requires_an_explicit_subject() -> None:
    with pytest.raises(AnalysisRequestError, match="requires an explicit subject"):
        validate_analysis_request(
            AnalysisRequest(
                analysis_type=AnalysisType.ENTITY_SUMMARY,
                question="Summarize it.",
            )
        )
