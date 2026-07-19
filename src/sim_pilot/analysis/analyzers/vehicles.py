"""Vehicle-performance and fleet-summary analyzers."""

from __future__ import annotations

from sim_pilot.analysis.analyzers.base import AnalyzerResult
from sim_pilot.analysis.analyzers.support import (
    add_result,
    filter_value,
    make_finding,
    requested_ids,
)
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
from sim_pilot.domain.world import Vehicle, WorldSnapshot


class VehiclePerformanceAnalyzer:
    analysis_type = AnalysisType.VEHICLE_PERFORMANCE

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del comparison
        vehicles = _selected_vehicles(request, current)
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        for vehicle in vehicles:
            if vehicle.profit_last_year < 0:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="negative_last_year_profit",
                        entity_ids=(vehicle.id,),
                        kind=FindingKind.OBSERVED_FACT,
                        severity=FindingSeverity.WARNING,
                        title=f"Unprofitable vehicle {vehicle.name}",
                        summary=f"The vehicle lost {abs(vehicle.profit_last_year)} last year.",
                        metric_name="profit_last_year",
                        metric_value=vehicle.profit_last_year,
                        confidence=EvidenceConfidence.HIGH,
                        evidence=(_vehicle_field(current, vehicle, "profit_last_year"),),
                        limitations=(
                            "New, redirected, or subsidized vehicles can be false positives.",
                        ),
                        recommendation_code="inspect_unprofitable_vehicle",
                    ),
                )
            elif vehicle.profit_this_year < 0:
                finding, _ = make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="negative_current_profit",
                    entity_ids=(vehicle.id,),
                    kind=FindingKind.OBSERVED_FACT,
                    severity=FindingSeverity.INFORMATIONAL,
                    title=f"Current-year loss for {vehicle.name}",
                    summary=f"Current-year profit is {vehicle.profit_this_year}.",
                    metric_name="profit_this_year",
                    metric_value=vehicle.profit_this_year,
                    confidence=EvidenceConfidence.HIGH,
                    evidence=(_vehicle_field(current, vehicle, "profit_this_year"),),
                    limitations=("The current accounting year may be incomplete.",),
                )
                findings.append(finding)
            if vehicle.age_days >= 7_305:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="old_vehicle",
                        entity_ids=(vehicle.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=FindingSeverity.OPPORTUNITY,
                        title=f"Older vehicle {vehicle.name}",
                        summary=f"The vehicle is {vehicle.age_days} days old.",
                        metric_name="age_days",
                        metric_value=vehicle.age_days,
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(_vehicle_field(current, vehicle, "age_days"),),
                        limitations=("Some vehicle sets have no meaningful obsolescence.",),
                        recommendation_code="review_old_vehicle",
                    ),
                )
            idle = vehicle.in_depot or vehicle.running_state.lower() in {"stopped", "idle"}
            if idle:
                severity = (
                    FindingSeverity.WARNING
                    if vehicle.profit_last_year < 0
                    else FindingSeverity.INFORMATIONAL
                )
                finding, recommendation = make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="idle_vehicle",
                    entity_ids=(vehicle.id,),
                    kind=FindingKind.OBSERVED_FACT,
                    severity=severity,
                    title=f"Idle or depot vehicle {vehicle.name}",
                    summary=(
                        f"Observed state is {vehicle.running_state}; in_depot={vehicle.in_depot}."
                    ),
                    metric_name="running_state",
                    metric_value=vehicle.running_state,
                    confidence=EvidenceConfidence.HIGH,
                    evidence=(
                        _vehicle_field(current, vehicle, "running_state"),
                        _vehicle_field(current, vehicle, "in_depot"),
                    ),
                    recommendation_code="inspect_idle_loss"
                    if severity is FindingSeverity.WARNING
                    else None,
                )
                findings.append(finding)
                if recommendation is not None:
                    recommendations.append(recommendation)
            if vehicle.route_id is None:
                finding, _ = make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="route_unavailable",
                    entity_ids=(vehicle.id,),
                    kind=FindingKind.DATA_QUALITY,
                    severity=FindingSeverity.INFORMATIONAL,
                    title=f"No usable route inference for {vehicle.name}",
                    summary="The canonical snapshot does not associate this vehicle with a route.",
                    confidence=EvidenceConfidence.HIGH,
                    evidence=(_vehicle_field(current, vehicle, "route_id"),),
                )
                findings.append(finding)
        findings = _rank_findings(findings, request)
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED if vehicles else AnalysisStatus.INSUFFICIENT_DATA,
            answer=f"Analyzed {len(vehicles)} vehicles and produced {len(findings)} findings.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=(
                "Vehicle classes are not normalized against each other unless filtered by type.",
            ),
        )


class FleetSummaryAnalyzer:
    analysis_type = AnalysisType.FLEET_SUMMARY

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del comparison
        vehicles = _selected_vehicles(request, current)
        counts: dict[str, int] = {}
        for vehicle in vehicles:
            counts[vehicle.type] = counts.get(vehicle.type, 0) + 1
        findings: list[AnalysisFinding] = []
        for vehicle_type, count in sorted(counts.items()):
            finding, _ = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code=f"fleet_count_{vehicle_type}",
                entity_ids=(observer_company(current).id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.INFORMATIONAL,
                title=f"{vehicle_type.title()} fleet count",
                summary=f"Observed {count} {vehicle_type} vehicles.",
                metric_name="vehicle_count",
                metric_value=count,
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id=observer_company(current).id,
                        field=f"vehicle_count.{vehicle_type}",
                        value=count,
                        inputs={"vehicle_type": vehicle_type, "count": count},
                    ),
                ),
            )
            findings.append(finding)
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED if vehicles else AnalysisStatus.INSUFFICIENT_DATA,
            answer=f"Observed fleet contains {len(vehicles)} vehicles across {len(counts)} types.",
            findings=tuple(findings),
        )


def _selected_vehicles(request: AnalysisRequest, snapshot: WorldSnapshot) -> list[Vehicle]:
    company_id = observer_company(snapshot).id
    ids = requested_ids(request, AnalysisSubjectType.VEHICLE)
    route_ids = requested_ids(request, AnalysisSubjectType.ROUTE)
    result: list[Vehicle] = []
    for vehicle in snapshot.vehicles:
        if vehicle.owner_id != company_id:
            continue
        if ids is not None and vehicle.id not in ids:
            continue
        if route_ids is not None and vehicle.route_id not in route_ids:
            continue
        values = {
            "entity_id": vehicle.id,
            "owner_id": vehicle.owner_id,
            "vehicle_type": vehicle.type,
            "route_id": vehicle.route_id,
            "running_state": vehicle.running_state,
            "in_depot": vehicle.in_depot,
            "profit_this_year": vehicle.profit_this_year,
            "profit_last_year": vehicle.profit_last_year,
            "age_days": vehicle.age_days,
        }
        if all(filter_value(request.filters, field, value) for field, value in values.items()):
            result.append(vehicle)
    return sorted(result, key=lambda item: item.id)


def _vehicle_field(snapshot: WorldSnapshot, vehicle: Vehicle, field: str):
    return field_evidence(
        snapshot,
        entity_type=AnalysisSubjectType.VEHICLE,
        entity_id=vehicle.id,
        field=field,
        value=getattr(vehicle, field),
    )


def _rank_findings(
    findings: list[AnalysisFinding], request: AnalysisRequest
) -> list[AnalysisFinding]:
    metric = (
        request.ranking.metric if request.ranking is not None else RankingMetric.PROFIT_LAST_YEAR
    )
    direction = (
        request.ranking.direction if request.ranking is not None else RankingDirection.ASCENDING
    )
    expected = {
        RankingMetric.PROFIT_THIS_YEAR: "profit_this_year",
        RankingMetric.PROFIT_LAST_YEAR: "profit_last_year",
        RankingMetric.AGE_DAYS: "age_days",
    }.get(metric)

    def key(item: AnalysisFinding) -> tuple[int, float, str]:
        metric_value = item.metric_value
        matched = item.metric_name == expected and isinstance(metric_value, (int, float))
        value = float(metric_value) if isinstance(metric_value, (int, float)) and matched else 0.0
        if direction is RankingDirection.DESCENDING:
            value = -value
        return (0 if matched else 1, value, item.finding_id)

    return sorted(findings, key=key)
