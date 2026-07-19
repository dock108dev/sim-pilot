"""Station and inferred-route performance analyzers."""

from __future__ import annotations

from statistics import median

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
    RankingDirection,
    RankingMetric,
)
from sim_pilot.analysis.evidence import field_evidence, metric_evidence, observer_company
from sim_pilot.domain.models import JsonValue
from sim_pilot.domain.world import WorldSnapshot

ROUTE_LIMITATION = (
    "Route identity is inferred from normalized orders and can change when orders or vehicle type "
    "change; vehicle renaming and snapshot ordering do not change it."
)


class StationPerformanceAnalyzer:
    analysis_type = AnalysisType.STATION_PERFORMANCE

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del comparison
        company_id = observer_company(current).id
        requested = requested_ids(request, AnalysisSubjectType.STATION)
        stations = sorted(
            (
                item
                for item in current.stations
                if item.owner_id == company_id and (requested is None or item.id in requested)
            ),
            key=lambda item: item.id,
        )
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        for station in stations:
            waiting = sum(item.waiting or 0 for item in station.waiting_cargo)
            pressure = waiting / max(station.vehicle_count, 1)
            finding, _ = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code="station_waiting_pressure",
                entity_ids=(station.id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.INFORMATIONAL,
                title=f"Waiting cargo at {station.name}",
                summary=(
                    f"Observed waiting cargo is {waiting}; descriptive cargo-per-vehicle pressure "
                    f"is {pressure:.1f}."
                ),
                metric_name="waiting_cargo",
                metric_value=waiting,
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.STATION,
                        entity_id=station.id,
                        field="waiting_pressure",
                        value=round(pressure, 4),
                        inputs={"waiting_cargo": waiting, "vehicle_count": station.vehicle_count},
                    ),
                ),
                limitations=("Waiting cargo alone does not establish congestion.",),
            )
            findings.append(finding)
            if waiting >= 500 and station.vehicle_count == 0:
                severity = (
                    FindingSeverity.WARNING if waiting >= 1_000 else FindingSeverity.OPPORTUNITY
                )
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="potentially_underserved_station",
                        entity_ids=(station.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=severity,
                        title=f"Potentially underserved station {station.name}",
                        summary=f"{waiting} cargo units are waiting with no observed vehicles.",
                        metric_name="waiting_cargo",
                        metric_value=waiting,
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            field_evidence(
                                current,
                                entity_type=AnalysisSubjectType.STATION,
                                entity_id=station.id,
                                field="vehicle_count",
                                value=station.vehicle_count,
                            ),
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.STATION,
                                entity_id=station.id,
                                field="waiting_cargo_total",
                                value=waiting,
                                inputs={"cargo_flow_count": len(station.waiting_cargo)},
                            ),
                        ),
                        limitations=(
                            "Transfers, recent cargo arrivals, outages, or storage designs can be "
                            "false positives.",
                        ),
                        recommendation_code="inspect_station_service",
                    ),
                )
            elif waiting >= 1_000 and station.vehicle_count == 1:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="single_vehicle_high_waiting",
                        entity_ids=(station.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=FindingSeverity.OPPORTUNITY,
                        title=f"High waiting cargo with one vehicle at {station.name}",
                        summary=f"{waiting} cargo units are waiting with one observed vehicle.",
                        metric_name="waiting_cargo",
                        metric_value=waiting,
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            field_evidence(
                                current,
                                entity_type=AnalysisSubjectType.STATION,
                                entity_id=station.id,
                                field="vehicle_count",
                                value=station.vehicle_count,
                            ),
                        ),
                        limitations=("This is not a capacity or congestion measurement.",),
                        recommendation_code="inspect_station_capacity",
                    ),
                )
        findings.sort(
            key=lambda item: (
                -(float(item.metric_value) if isinstance(item.metric_value, (int, float)) else 0),
                item.finding_id,
            )
        )
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED if stations else AnalysisStatus.INSUFFICIENT_DATA,
            answer=f"Analyzed {len(stations)} stations without inferring congestion.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
        )


class RoutePerformanceAnalyzer:
    analysis_type = AnalysisType.ROUTE_PERFORMANCE

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del comparison
        company_id = observer_company(current).id
        requested = requested_ids(request, AnalysisSubjectType.ROUTE)
        routes = sorted(
            (
                item
                for item in current.routes
                if item.owner_id == company_id and (requested is None or item.id in requested)
            ),
            key=lambda item: item.id,
        )
        vehicles = {item.id: item for item in current.vehicles}
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        limitations: list[str] = [ROUTE_LIMITATION]
        for route in routes:
            members = [vehicles[item] for item in route.vehicle_ids if item in vehicles]
            missing = sorted(set(route.vehicle_ids) - vehicles.keys())
            if missing:
                limitations.append(f"Route {route.id} has {len(missing)} unresolved vehicle IDs.")
            if not members:
                continue
            profits = [item.profit_last_year for item in members]
            aggregate = sum(profits)
            route_median = median(profits)
            negative = sum(value < 0 for value in profits)
            share = negative / len(members)
            severity = FindingSeverity.WARNING if aggregate < 0 else FindingSeverity.INFORMATIONAL
            metric_inputs: dict[str, JsonValue] = {
                "vehicle_ids": [item.id for item in members],
                "profit_last_year": list(profits),
                "median_profit": route_median,
            }
            result = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code="negative_route_profit" if aggregate < 0 else "route_profit_summary",
                entity_ids=(route.id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=severity,
                title=f"Route {route.id} profit summary",
                summary=(
                    f"Last-year aggregate profit is {aggregate}, median profit is "
                    f"{route_median:g}, and {negative} of {len(members)} vehicles lost money."
                ),
                metric_name="route_aggregate_profit",
                metric_value=aggregate,
                confidence=EvidenceConfidence.MEDIUM,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.ROUTE,
                        entity_id=route.id,
                        field="route_aggregate_profit",
                        value=aggregate,
                        inputs=metric_inputs,
                    ),
                ),
                limitations=(ROUTE_LIMITATION,),
                recommendation_code="inspect_negative_route" if aggregate < 0 else None,
            )
            add_result(findings, recommendations, result)
            if len(members) >= 2 and share >= 0.5:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="negative_route_vehicle_share",
                        entity_ids=(route.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=FindingSeverity.WARNING,
                        title=f"Many unprofitable vehicles on route {route.id}",
                        summary=f"{share:.1%} of observed route vehicles lost money last year.",
                        metric_name="negative_profit_share",
                        metric_value=round(share, 4),
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.ROUTE,
                                entity_id=route.id,
                                field="negative_profit_share",
                                value=round(share, 4),
                                inputs={
                                    "negative_vehicles": negative,
                                    "vehicle_count": len(members),
                                },
                            ),
                        ),
                        limitations=(ROUTE_LIMITATION,),
                        recommendation_code="inspect_route_vehicles",
                    ),
                )
            if len(members) == 1:
                finding, _ = make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="single_vehicle_route",
                    entity_ids=(route.id,),
                    kind=FindingKind.OBSERVED_FACT,
                    severity=FindingSeverity.INFORMATIONAL,
                    title=f"Single-vehicle route {route.id}",
                    summary="The inferred route has one observed vehicle.",
                    metric_name="vehicle_count",
                    metric_value=1,
                    confidence=EvidenceConfidence.HIGH,
                    evidence=(
                        field_evidence(
                            current,
                            entity_type=AnalysisSubjectType.ROUTE,
                            entity_id=route.id,
                            field="vehicle_ids",
                            value=list(route.vehicle_ids),
                        ),
                    ),
                    limitations=("A single vehicle is not evidence of insufficient capacity.",),
                )
                findings.append(finding)
        findings.sort(key=lambda item: _route_sort_key(item, request))
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED if routes else AnalysisStatus.INSUFFICIENT_DATA,
            answer=f"Analyzed {len(routes)} inferred routes.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=tuple(dict.fromkeys(limitations)),
        )


def _route_sort_key(item: AnalysisFinding, request: AnalysisRequest) -> tuple[int, float, str]:
    value = item.metric_value
    ranking = request.ranking
    matched = bool(
        (ranking is None or ranking.metric is RankingMetric.ROUTE_AGGREGATE_PROFIT)
        and item.metric_name == "route_aggregate_profit"
        and isinstance(value, (int, float))
    )
    numeric = float(value) if matched and isinstance(value, (int, float)) else 0.0
    if ranking is not None and ranking.direction is RankingDirection.DESCENDING:
        numeric = -numeric
    return (0 if matched else 1, numeric, item.finding_id)
