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
    AnalysisPopulation,
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
        if request.ranking is not None:
            return _ranked_vehicle_result(request, current, vehicles)
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
                        summary=(
                            f"{vehicle.name} lost £{abs(vehicle.profit_last_year):,} last year."
                        ),
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
        observed_company_vehicles = any(
            item.owner_id == observer_company(current).id for item in current.vehicles
        )
        clean_no_match = not vehicles and bool(request.filters) and observed_company_vehicles
        return AnalyzerResult(
            status=(
                AnalysisStatus.COMPLETED
                if vehicles or clean_no_match
                else AnalysisStatus.INSUFFICIENT_DATA
            ),
            answer=(
                "No observed vehicles matched the requested filters."
                if clean_no_match
                else f"Analyzed {len(vehicles)} vehicles and produced {len(findings)} findings."
            ),
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=(
                "Vehicle classes are not normalized against each other unless filtered by type.",
            ),
            population=AnalysisPopulation(
                eligible_count=len(vehicles),
                evaluated_count=len(vehicles),
                excluded_count=0,
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
        if (
            request.ranking is not None
            and request.ranking.metric is RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT
        ):
            return _vehicle_type_profit_result(request, current, vehicles)
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
            population=AnalysisPopulation(
                eligible_count=len(counts),
                evaluated_count=len(counts),
                excluded_count=0,
                metric=RankingMetric.VEHICLE_COUNT,
            ),
        )


def _ranked_vehicle_result(
    request: AnalysisRequest,
    snapshot: WorldSnapshot,
    vehicles: list[Vehicle],
) -> AnalyzerResult:
    assert request.ranking is not None
    metric = request.ranking.metric
    field = {
        RankingMetric.PROFIT_THIS_YEAR: "profit_this_year",
        RankingMetric.PROFIT_LAST_YEAR: "profit_last_year",
        RankingMetric.AGE_DAYS: "age_days",
    }[metric]
    reverse = request.ranking.direction is RankingDirection.DESCENDING
    ranked = sorted(
        vehicles,
        key=lambda item: (
            -getattr(item, field) if reverse else getattr(item, field),
            item.id,
        ),
    )
    findings: list[AnalysisFinding] = []
    recommendations: list[AnalysisRecommendation] = []
    for position, vehicle in enumerate(ranked[: request.ranking.limit], start=1):
        value = getattr(vehicle, field)
        finding, recommendation = make_finding(
            snapshot=snapshot,
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            code=f"ranked_{field}_{position}",
            entity_ids=(vehicle.id,),
            kind=FindingKind.OBSERVED_FACT,
            severity=FindingSeverity.INFORMATIONAL,
            title=f"#{position} {vehicle.name} by {field.replace('_', ' ')}",
            summary=f"{vehicle.name} ranks #{position} with {field}={value}.",
            metric_name=metric.value,
            metric_value=value,
            confidence=EvidenceConfidence.HIGH,
            evidence=(_vehicle_field(snapshot, vehicle, field),),
            limitations=(
                ("A negative accounting result warrants inspection before any action.",)
                if field in {"profit_this_year", "profit_last_year"} and value < 0
                else ()
            ),
            recommendation_code=(
                "inspect_ranked_unprofitable_vehicle"
                if field in {"profit_this_year", "profit_last_year"} and value < 0
                else None
            ),
        )
        findings.append(finding)
        if recommendation is not None:
            recommendations.append(recommendation)
    return AnalyzerResult(
        status=AnalysisStatus.COMPLETED if vehicles else AnalysisStatus.INSUFFICIENT_DATA,
        answer=f"Ranked {len(vehicles)} eligible vehicles by {metric.value}.",
        findings=tuple(findings),
        recommendations=tuple(recommendations),
        limitations=(
            "Vehicle classes are not normalized against each other unless filtered by type.",
        ),
        population=AnalysisPopulation(
            eligible_count=len(vehicles),
            evaluated_count=len(vehicles),
            excluded_count=0,
            metric=metric,
            direction=request.ranking.direction,
        ),
    )


def _vehicle_type_profit_result(
    request: AnalysisRequest,
    snapshot: WorldSnapshot,
    vehicles: list[Vehicle],
) -> AnalyzerResult:
    assert request.ranking is not None
    groups: dict[str, list[Vehicle]] = {}
    for vehicle in vehicles:
        groups.setdefault(vehicle.type, []).append(vehicle)
    values = [
        (
            vehicle_type,
            sum(item.profit_last_year for item in members),
            sum(item.profit_last_year < 0 for item in members),
            len(members),
        )
        for vehicle_type, members in groups.items()
    ]
    reverse = request.ranking.direction is RankingDirection.DESCENDING
    values.sort(key=lambda item: (-item[1] if reverse else item[1], item[0]))
    findings: list[AnalysisFinding] = []
    for position, (vehicle_type, profit, negative, count) in enumerate(
        values[: request.ranking.limit], start=1
    ):
        finding, _ = make_finding(
            snapshot=snapshot,
            analysis_type=AnalysisType.FLEET_SUMMARY,
            code=f"vehicle_type_profit_{vehicle_type}",
            entity_ids=(observer_company(snapshot).id,),
            kind=FindingKind.OBSERVED_FACT,
            severity=(FindingSeverity.WARNING if profit < 0 else FindingSeverity.INFORMATIONAL),
            title=f"#{position} {vehicle_type.title()} aggregate profit",
            summary=(
                f"{vehicle_type.title()} vehicles produced {profit} aggregate last-year profit; "
                f"{negative} of {count} lost money."
            ),
            metric_name=RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT.value,
            metric_value=profit,
            confidence=EvidenceConfidence.HIGH,
            evidence=(
                metric_evidence(
                    snapshot,
                    entity_type=AnalysisSubjectType.COMPANY,
                    entity_id=observer_company(snapshot).id,
                    field=f"vehicle_type_aggregate_profit.{vehicle_type}",
                    value=profit,
                    inputs={
                        "vehicle_type": vehicle_type,
                        "vehicle_count": count,
                        "negative_vehicle_count": negative,
                    },
                ),
            ),
        )
        findings.append(finding)
    return AnalyzerResult(
        status=AnalysisStatus.COMPLETED if groups else AnalysisStatus.INSUFFICIENT_DATA,
        answer=f"Ranked {len(groups)} vehicle types by aggregate last-year profit.",
        findings=tuple(findings),
        population=AnalysisPopulation(
            eligible_count=len(groups),
            evaluated_count=len(groups),
            excluded_count=0,
            metric=RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
            direction=request.ranking.direction,
        ),
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
