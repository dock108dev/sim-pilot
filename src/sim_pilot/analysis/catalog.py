"""Closed Phase 8B analysis capabilities and semantic request validation."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from sim_pilot.analysis.contracts import (
    AnalysisFilterField,
    AnalysisRequest,
    AnalysisSubjectType,
    AnalysisType,
    RankingMetric,
)
from sim_pilot.analysis.errors import AnalysisRequestError


class ComparisonRequirement(StrEnum):
    OPTIONAL = "optional"
    REQUIRED = "required"


class AnalysisCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    analysis_type: AnalysisType
    subjects: frozenset[AnalysisSubjectType]
    filters: frozenset[AnalysisFilterField] = frozenset()
    ranking_metrics: frozenset[RankingMetric] = frozenset()
    required_coverage: frozenset[str] = frozenset()
    comparison: ComparisonRequirement = ComparisonRequirement.OPTIONAL
    subject_required: bool = False


def _capability(
    analysis_type: AnalysisType,
    *,
    subjects: tuple[AnalysisSubjectType, ...],
    filters: tuple[AnalysisFilterField, ...] = (),
    ranking: tuple[RankingMetric, ...] = (),
    coverage: tuple[str, ...] = (),
    comparison: ComparisonRequirement = ComparisonRequirement.OPTIONAL,
    subject_required: bool = False,
) -> AnalysisCapability:
    return AnalysisCapability(
        analysis_type=analysis_type,
        subjects=frozenset(subjects),
        filters=frozenset(filters),
        ranking_metrics=frozenset(ranking),
        required_coverage=frozenset(coverage),
        comparison=comparison,
        subject_required=subject_required,
    )


_WORLD_COMPANY = (AnalysisSubjectType.WORLD, AnalysisSubjectType.COMPANY)
_VEHICLE_FILTERS = (
    AnalysisFilterField.ENTITY_ID,
    AnalysisFilterField.OWNER_ID,
    AnalysisFilterField.VEHICLE_TYPE,
    AnalysisFilterField.ROUTE_ID,
    AnalysisFilterField.RUNNING_STATE,
    AnalysisFilterField.IN_DEPOT,
    AnalysisFilterField.PROFIT_THIS_YEAR,
    AnalysisFilterField.PROFIT_LAST_YEAR,
    AnalysisFilterField.AGE_DAYS,
)

DEFAULT_ANALYSIS_CATALOG = MappingProxyType(
    {
        AnalysisType.COMPANY_HEALTH: _capability(
            AnalysisType.COMPANY_HEALTH,
            subjects=_WORLD_COMPANY,
            coverage=("companies", "vehicles"),
        ),
        AnalysisType.FINANCIAL_SUMMARY: _capability(
            AnalysisType.FINANCIAL_SUMMARY,
            subjects=_WORLD_COMPANY,
            ranking=(
                RankingMetric.CASH,
                RankingMetric.LOAN,
                RankingMetric.COMPANY_VALUE,
                RankingMetric.INCOME,
                RankingMetric.EXPENSES,
            ),
            coverage=("companies",),
        ),
        AnalysisType.VEHICLE_PERFORMANCE: _capability(
            AnalysisType.VEHICLE_PERFORMANCE,
            subjects=(
                AnalysisSubjectType.WORLD,
                AnalysisSubjectType.COMPANY,
                AnalysisSubjectType.ROUTE,
                AnalysisSubjectType.VEHICLE,
            ),
            filters=_VEHICLE_FILTERS,
            ranking=(
                RankingMetric.PROFIT_THIS_YEAR,
                RankingMetric.PROFIT_LAST_YEAR,
                RankingMetric.AGE_DAYS,
            ),
            coverage=("vehicles",),
        ),
        AnalysisType.STATION_PERFORMANCE: _capability(
            AnalysisType.STATION_PERFORMANCE,
            subjects=(
                AnalysisSubjectType.WORLD,
                AnalysisSubjectType.COMPANY,
                AnalysisSubjectType.STATION,
            ),
            filters=(
                AnalysisFilterField.ENTITY_ID,
                AnalysisFilterField.OWNER_ID,
                AnalysisFilterField.STATION_ID,
            ),
            ranking=(RankingMetric.WAITING_CARGO, RankingMetric.VEHICLE_COUNT),
            coverage=("stations", "cargo"),
        ),
        AnalysisType.ROUTE_PERFORMANCE: _capability(
            AnalysisType.ROUTE_PERFORMANCE,
            subjects=(
                AnalysisSubjectType.WORLD,
                AnalysisSubjectType.COMPANY,
                AnalysisSubjectType.ROUTE,
            ),
            filters=(
                AnalysisFilterField.ENTITY_ID,
                AnalysisFilterField.OWNER_ID,
                AnalysisFilterField.ROUTE_ID,
                AnalysisFilterField.VEHICLE_TYPE,
            ),
            ranking=(
                RankingMetric.ROUTE_AGGREGATE_PROFIT,
                RankingMetric.ROUTE_MEDIAN_PROFIT,
                RankingMetric.VEHICLE_COUNT,
            ),
            coverage=("routes", "vehicles"),
        ),
        AnalysisType.SERVICE_COVERAGE: _capability(
            AnalysisType.SERVICE_COVERAGE,
            subjects=_WORLD_COMPANY,
            filters=(AnalysisFilterField.TOWN_ID, AnalysisFilterField.INDUSTRY_ID),
            ranking=(
                RankingMetric.POPULATION,
                RankingMetric.PRODUCTION,
                RankingMetric.OPPORTUNITY_SCORE,
            ),
            coverage=("towns", "industries", "stations"),
        ),
        AnalysisType.INDUSTRY_OPPORTUNITIES: _capability(
            AnalysisType.INDUSTRY_OPPORTUNITIES,
            subjects=(AnalysisSubjectType.WORLD, AnalysisSubjectType.INDUSTRY),
            filters=(AnalysisFilterField.ENTITY_ID, AnalysisFilterField.INDUSTRY_ID),
            ranking=(RankingMetric.PRODUCTION, RankingMetric.OPPORTUNITY_SCORE),
            coverage=("industries", "stations", "cargo"),
        ),
        AnalysisType.TOWN_COVERAGE: _capability(
            AnalysisType.TOWN_COVERAGE,
            subjects=(AnalysisSubjectType.WORLD, AnalysisSubjectType.TOWN),
            filters=(AnalysisFilterField.ENTITY_ID, AnalysisFilterField.TOWN_ID),
            ranking=(RankingMetric.POPULATION, RankingMetric.OPPORTUNITY_SCORE),
            coverage=("towns", "stations"),
        ),
        AnalysisType.FLEET_SUMMARY: _capability(
            AnalysisType.FLEET_SUMMARY,
            subjects=_WORLD_COMPANY,
            filters=_VEHICLE_FILTERS,
            coverage=("companies", "vehicles", "routes"),
        ),
        AnalysisType.WORLD_CHANGES: _capability(
            AnalysisType.WORLD_CHANGES,
            subjects=(AnalysisSubjectType.WORLD,),
            ranking=(RankingMetric.MATERIALITY,),
        ),
        AnalysisType.ANOMALY_DETECTION: _capability(
            AnalysisType.ANOMALY_DETECTION,
            subjects=_WORLD_COMPANY,
            ranking=(RankingMetric.MATERIALITY,),
            comparison=ComparisonRequirement.REQUIRED,
        ),
        AnalysisType.PRIORITY_REVIEW: _capability(
            AnalysisType.PRIORITY_REVIEW,
            subjects=_WORLD_COMPANY,
            ranking=(RankingMetric.MATERIALITY,),
            coverage=("companies", "vehicles", "stations", "routes", "towns", "industries"),
        ),
        AnalysisType.ENTITY_SUMMARY: _capability(
            AnalysisType.ENTITY_SUMMARY,
            subjects=(
                AnalysisSubjectType.COMPANY,
                AnalysisSubjectType.TOWN,
                AnalysisSubjectType.INDUSTRY,
                AnalysisSubjectType.STATION,
                AnalysisSubjectType.VEHICLE,
                AnalysisSubjectType.ROUTE,
            ),
            filters=(AnalysisFilterField.ENTITY_ID,),
            subject_required=True,
        ),
    }
)


def capability_for(analysis_type: AnalysisType) -> AnalysisCapability:
    return DEFAULT_ANALYSIS_CATALOG[analysis_type]


def validate_analysis_request(request: AnalysisRequest) -> AnalysisCapability:
    capability = capability_for(request.analysis_type)
    if capability.subject_required and request.subject_type is None:
        raise AnalysisRequestError(f"{request.analysis_type.value} requires an explicit subject")
    if request.subject_type is not None and request.subject_type not in capability.subjects:
        raise AnalysisRequestError(
            f"{request.subject_type.value} is not a supported subject for "
            f"{request.analysis_type.value}"
        )
    unsupported_filters = sorted(
        {item.field for item in request.filters} - capability.filters,
        key=lambda value: value.value,
    )
    if unsupported_filters:
        names = ", ".join(item.value for item in unsupported_filters)
        raise AnalysisRequestError(
            f"unsupported filters for {request.analysis_type.value}: {names}"
        )
    if request.ranking is not None and request.ranking.metric not in capability.ranking_metrics:
        raise AnalysisRequestError(
            f"ranking metric {request.ranking.metric.value} is unsupported for "
            f"{request.analysis_type.value}"
        )
    if (
        capability.comparison is ComparisonRequirement.REQUIRED
        and request.comparison_snapshot_id is None
    ):
        raise AnalysisRequestError(f"{request.analysis_type.value} requires a comparison snapshot")
    return capability
