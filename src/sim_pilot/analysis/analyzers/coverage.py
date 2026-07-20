"""Deterministic town, industry, and combined service-coverage analysis."""

from __future__ import annotations

from sim_pilot.analysis.analyzers.base import AnalyzerResult
from sim_pilot.analysis.analyzers.support import add_result, make_finding, requested_ids
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.analysis.evidence import metric_evidence, observer_company
from sim_pilot.domain.world import Coordinates, WorldSnapshot


class TownCoverageAnalyzer:
    analysis_type = AnalysisType.TOWN_COVERAGE

    def analyze(
        self, request: AnalysisRequest, current: WorldSnapshot, comparison: WorldSnapshot | None
    ) -> AnalyzerResult:
        del comparison
        return _town_analysis(request, current, self.analysis_type)


class IndustryOpportunitiesAnalyzer:
    analysis_type = AnalysisType.INDUSTRY_OPPORTUNITIES

    def analyze(
        self, request: AnalysisRequest, current: WorldSnapshot, comparison: WorldSnapshot | None
    ) -> AnalyzerResult:
        del comparison
        return _industry_analysis(request, current, self.analysis_type)


class ServiceCoverageAnalyzer:
    analysis_type = AnalysisType.SERVICE_COVERAGE

    def analyze(
        self, request: AnalysisRequest, current: WorldSnapshot, comparison: WorldSnapshot | None
    ) -> AnalyzerResult:
        del comparison
        towns = _town_analysis(request, current, self.analysis_type)
        industries = _industry_analysis(request, current, self.analysis_type)
        return AnalyzerResult(
            status=(
                AnalysisStatus.INSUFFICIENT_DATA
                if towns.status is AnalysisStatus.INSUFFICIENT_DATA
                and industries.status is AnalysisStatus.INSUFFICIENT_DATA
                else AnalysisStatus.COMPLETED
            ),
            answer=(
                f"Found {len(towns.findings)} unserved-town and "
                f"{len(industries.findings)} unserved-industry opportunities."
            ),
            findings=tuple(sorted((*towns.findings, *industries.findings), key=_score_sort)),
            recommendations=(*towns.recommendations, *industries.recommendations),
            limitations=tuple(dict.fromkeys((*towns.limitations, *industries.limitations))),
        )


def _town_analysis(
    request: AnalysisRequest, current: WorldSnapshot, analysis_type: AnalysisType
) -> AnalyzerResult:
    requested = requested_ids(request, AnalysisSubjectType.TOWN)
    station_coordinates = _company_station_coordinates(current)
    findings: list[AnalysisFinding] = []
    recommendations: list[AnalysisRecommendation] = []
    for town in sorted(current.towns, key=lambda item: item.id):
        if requested is not None and town.id not in requested:
            continue
        if (town.station_count or 0) > 0:
            continue
        distance = _nearest_distance(town.coordinates, station_coordinates)
        population_points = 60 * min(town.population / 5_000, 1)
        proximity_points = 0.0 if distance is None else 30 * (1 - min(distance / 50, 1))
        growing = town.growth_state is not None and town.growth_state.lower() in {
            "growing",
            "growth",
            "active",
        }
        score = round(population_points + proximity_points + (10 if growing else 0), 2)
        add_result(
            findings,
            recommendations,
            make_finding(
                snapshot=current,
                analysis_type=analysis_type,
                code="unserved_town_opportunity",
                entity_ids=(town.id,),
                kind=FindingKind.INFERRED_FINDING,
                severity=FindingSeverity.OPPORTUNITY,
                title=f"Unserved town {town.name}",
                summary=(
                    f"No selected-company station is observed for population {town.population}; "
                    f"opportunity score is {score}."
                ),
                metric_name="opportunity_score",
                metric_value=score,
                confidence=EvidenceConfidence.MEDIUM,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.TOWN,
                        entity_id=town.id,
                        field="town_opportunity_score",
                        value=score,
                        inputs={
                            "population": town.population,
                            "nearest_station_distance": distance,
                            "growing": growing,
                            "population_points": round(population_points, 2),
                            "proximity_points": round(proximity_points, 2),
                            "growth_bonus": 10 if growing else 0,
                        },
                    ),
                ),
                limitations=(
                    "Population is only an investigation heuristic; terrain, authority, "
                    "competitors, destinations, and profitability are not evaluated.",
                ),
                recommendation_code="investigate_unserved_town",
            ),
        )
    findings.sort(key=_score_sort)
    return AnalyzerResult(
        status=AnalysisStatus.COMPLETED if current.towns else AnalysisStatus.INSUFFICIENT_DATA,
        answer=f"Found {len(findings)} towns without an observed company station.",
        findings=tuple(findings),
        recommendations=tuple(recommendations),
        limitations=("Town service is proximity-based and does not prove passenger demand.",),
    )


def _industry_analysis(
    request: AnalysisRequest, current: WorldSnapshot, analysis_type: AnalysisType
) -> AnalyzerResult:
    requested = requested_ids(request, AnalysisSubjectType.INDUSTRY)
    station_coordinates = _company_station_coordinates(current)
    findings: list[AnalysisFinding] = []
    recommendations: list[AnalysisRecommendation] = []
    for industry in sorted(current.industries, key=lambda item: item.id):
        if requested is not None and industry.id not in requested:
            continue
        if industry.nearby_station_ids:
            continue
        production = sum(item.produced or 0 for item in industry.production)
        distance = _nearest_distance(industry.coordinates, station_coordinates)
        production_points = 70 * min(production / 1_000, 1)
        proximity_points = 0.0 if distance is None else 30 * (1 - min(distance / 50, 1))
        score = round(production_points + proximity_points, 2)
        add_result(
            findings,
            recommendations,
            make_finding(
                snapshot=current,
                analysis_type=analysis_type,
                code="unserved_industry_opportunity",
                entity_ids=(industry.id,),
                kind=FindingKind.INFERRED_FINDING,
                severity=FindingSeverity.OPPORTUNITY,
                title=f"Unserved industry {industry.name}",
                summary=(
                    f"{industry.name} has no observed selected-company nearby station; "
                    f"production is {production} and opportunity score is {score}."
                ),
                metric_name="opportunity_score",
                metric_value=score,
                confidence=EvidenceConfidence.MEDIUM,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.INDUSTRY,
                        entity_id=industry.id,
                        field="industry_opportunity_score",
                        value=score,
                        inputs={
                            "production": production,
                            "nearest_station_distance": distance,
                            "production_points": round(production_points, 2),
                            "proximity_points": round(proximity_points, 2),
                        },
                    ),
                ),
                limitations=(
                    "Cargo compatibility, consumers, terrain, competitors, and profitability "
                    "are not evaluated.",
                ),
                recommendation_code="investigate_unserved_industry",
            ),
        )
    findings.sort(key=_score_sort)
    return AnalyzerResult(
        status=AnalysisStatus.COMPLETED if current.industries else AnalysisStatus.INSUFFICIENT_DATA,
        answer=f"Found {len(findings)} industries without an observed company station.",
        findings=tuple(findings),
        recommendations=tuple(recommendations),
        limitations=("Opportunity scores identify investigation targets, not predicted profit.",),
    )


def _company_station_coordinates(snapshot: WorldSnapshot) -> tuple[Coordinates, ...]:
    company_id = observer_company(snapshot).id
    return tuple(item.coordinates for item in snapshot.stations if item.owner_id == company_id)


def _nearest_distance(origin: Coordinates, values: tuple[Coordinates, ...]) -> int | None:
    if not values:
        return None
    return min(abs(origin.x - item.x) + abs(origin.y - item.y) for item in values)


def _score_sort(item: AnalysisFinding) -> tuple[float, str]:
    value = item.metric_value
    score = float(value) if isinstance(value, (int, float)) else 0.0
    return -score, item.finding_id
