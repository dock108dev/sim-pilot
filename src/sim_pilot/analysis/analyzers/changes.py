"""Typed change, bounded anomaly, entity-summary, and priority analyzers."""

from __future__ import annotations

from sim_pilot.analysis.analyzers.base import AnalyzerResult
from sim_pilot.analysis.analyzers.coverage import (
    IndustryOpportunitiesAnalyzer,
    TownCoverageAnalyzer,
)
from sim_pilot.analysis.analyzers.financial import CompanyHealthAnalyzer
from sim_pilot.analysis.analyzers.network import (
    RoutePerformanceAnalyzer,
    StationPerformanceAnalyzer,
)
from sim_pilot.analysis.analyzers.support import (
    add_result,
    make_finding,
    percentage_change,
    priority_score,
)
from sim_pilot.analysis.analyzers.vehicles import VehiclePerformanceAnalyzer
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisPopulation,
    AnalysisRecommendation,
    AnalysisRequest,
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
)
from sim_pilot.analysis.evidence import field_evidence, observer_company
from sim_pilot.domain.models import JsonValue
from sim_pilot.domain.world import (
    CargoFlow,
    CoverageChanged,
    CoverageStatus,
    EntityAdded,
    EntityRemoved,
    FieldChanged,
    WorldSnapshot,
)

CURRENCY_LIMITATION = "Currency thresholds vary with inflation and economy settings."
ROUTE_COMPARISON_LIMITATION = (
    "Route IDs are order-signature identities; order or vehicle-type changes can appear as route "
    "removal and addition."
)


class WorldChangesAnalyzer:
    analysis_type = AnalysisType.WORLD_CHANGES

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        if comparison is None:
            return AnalyzerResult(
                status=AnalysisStatus.INSUFFICIENT_DATA,
                answer="A compatible comparison snapshot is required to evaluate changes.",
            )
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        for index, change in enumerate(current.changes):
            code = f"change_{index}_{change.change_type}"
            if isinstance(change, EntityAdded):
                severity = FindingSeverity.INFORMATIONAL
                title = f"{change.entity_type} added"
                summary = f"Observed new {change.entity_type} {change.entity_id}."
                entity_type = _subject(change.entity_type)
                entity_id = change.entity_id
                field = "entity_presence"
                value: JsonValue = True
                previous: JsonValue = False
            elif isinstance(change, EntityRemoved):
                severity = FindingSeverity.WARNING
                title = f"{change.entity_type} removed"
                summary = f"Previously observed {change.entity_type} {change.entity_id} is absent."
                entity_type = _subject(change.entity_type)
                entity_id = change.entity_id
                field = "entity_presence"
                value = False
                previous = True
            elif isinstance(change, CoverageChanged):
                severity = (
                    FindingSeverity.WARNING
                    if change.after is not CoverageStatus.AVAILABLE
                    else FindingSeverity.INFORMATIONAL
                )
                title = f"{change.category} coverage changed"
                summary = f"Coverage changed from {change.before.value} to {change.after.value}."
                entity_type = None
                entity_id = None
                field = f"coverage.{change.category}"
                value = change.after.value
                previous = change.before.value
            else:
                assert isinstance(change, FieldChanged)
                severity = _field_change_severity(change)
                title = f"{change.entity_type} {change.field} changed"
                summary = f"{change.field} changed from {change.before} to {change.after}."
                entity_type = _subject(change.entity_type)
                entity_id = change.entity_id
                field = change.field
                value = change.after
                previous = change.before
            evidence = EvidenceReference(
                source_type=EvidenceSourceType.SNAPSHOT_CHANGE,
                snapshot_id=current.metadata.snapshot_id,
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
                observed_value=value,
                comparison_snapshot_id=current.changes_from_snapshot_id,
                comparison_value=previous,
            )
            result = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code=code,
                entity_ids=() if entity_id is None else (entity_id,),
                kind=(
                    FindingKind.DATA_QUALITY
                    if isinstance(change, CoverageChanged)
                    else FindingKind.OBSERVED_FACT
                ),
                severity=severity,
                title=title,
                summary=summary,
                confidence=EvidenceConfidence.HIGH,
                evidence=(evidence,),
                metric_name=field,
                metric_value=value,
                comparison_value=previous,
                limitations=(
                    (ROUTE_COMPARISON_LIMITATION,)
                    if entity_id is not None and entity_type is AnalysisSubjectType.ROUTE
                    else ()
                ),
                recommendation_code="inspect_material_change"
                if severity in {FindingSeverity.WARNING, FindingSeverity.CRITICAL}
                else None,
            )
            add_result(findings, recommendations, result)
        if not current.metadata.complete:
            add_result(findings, recommendations, _incomplete_snapshot(current, self.analysis_type))
        subject_findings = [
            item
            for item in findings
            if request.subject_type in {None, AnalysisSubjectType.WORLD}
            or any(evidence.entity_type is request.subject_type for evidence in item.evidence)
        ]
        requested_metric = (
            None if request.answer_intent is None else request.answer_intent.requested_metric
        )
        findings = (
            subject_findings
            if requested_metric is None
            else [item for item in subject_findings if item.metric_name == requested_metric.value]
        )
        retained_ids = {item.finding_id for item in findings}
        recommendations = [
            item
            for item in recommendations
            if set(item.supporting_finding_ids).issubset(retained_ids)
        ]
        findings.sort(key=_priority_sort)
        limitations: tuple[str, ...] = ()
        if not current.changes:
            limitations = (
                "No canonical typed changes were supplied; this analyzer does not reconstruct "
                "adapter diffs.",
            )
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer=f"Observed {len(current.changes)} canonical world changes.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=limitations,
            population=AnalysisPopulation(
                eligible_count=len(subject_findings),
                evaluated_count=len(findings),
                excluded_count=len(subject_findings) - len(findings),
                exclusion_reasons=(
                    ("Changes without the requested metric were excluded.",)
                    if len(subject_findings) > len(findings)
                    else ()
                ),
                metric=requested_metric,
                period=(None if request.answer_intent is None else request.answer_intent.period),
            ),
        )


class AnomalyDetectionAnalyzer:
    analysis_type = AnalysisType.ANOMALY_DETECTION

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del request
        if comparison is None:
            return AnalyzerResult(
                status=AnalysisStatus.INSUFFICIENT_DATA,
                answer="An explicit comparison snapshot is required.",
            )
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        company = observer_company(current)
        previous_company = next(
            (item for item in comparison.companies if item.id == company.id), None
        )
        if previous_company is not None:
            cash_delta = company.cash - previous_company.cash
            if (
                cash_delta < 0
                and percentage_change(company.cash, previous_company.cash) >= 0.25
                and abs(cash_delta) >= 250_000
            ):
                add_result(
                    findings,
                    recommendations,
                    _change_finding(
                        current=current,
                        comparison=comparison,
                        code="cash_drop_anomaly",
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id=company.id,
                        field="cash",
                        value=company.cash,
                        previous=previous_company.cash,
                        delta=cash_delta,
                        title="Large observed cash drop",
                        limitation=CURRENCY_LIMITATION,
                    ),
                )
            debt_delta = company.loan - previous_company.loan
            if (
                debt_delta > 0
                and percentage_change(company.loan, previous_company.loan) >= 0.1
                and debt_delta >= 50_000
            ):
                add_result(
                    findings,
                    recommendations,
                    _change_finding(
                        current=current,
                        comparison=comparison,
                        code="debt_increase_anomaly",
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id=company.id,
                        field="loan",
                        value=company.loan,
                        previous=previous_company.loan,
                        delta=debt_delta,
                        title="Material observed debt increase",
                        limitation=CURRENCY_LIMITATION,
                    ),
                )
        previous_vehicles = {item.id: item for item in comparison.vehicles}
        for vehicle in current.vehicles:
            previous = previous_vehicles.get(vehicle.id)
            if previous is None:
                continue
            delta = vehicle.profit_last_year - previous.profit_last_year
            if (
                delta < 0
                and percentage_change(vehicle.profit_last_year, previous.profit_last_year) >= 0.5
                and abs(delta) >= 20_000
            ):
                add_result(
                    findings,
                    recommendations,
                    _change_finding(
                        current=current,
                        comparison=comparison,
                        code="vehicle_profit_drop",
                        entity_type=AnalysisSubjectType.VEHICLE,
                        entity_id=vehicle.id,
                        field="profit_last_year",
                        value=vehicle.profit_last_year,
                        previous=previous.profit_last_year,
                        delta=delta,
                        title=f"Large profit drop for {vehicle.name}",
                        limitation=CURRENCY_LIMITATION,
                    ),
                )
        previous_stations = {item.id: item for item in comparison.stations}
        for station in current.stations:
            previous = previous_stations.get(station.id)
            if previous is None:
                continue
            waiting = _waiting(station.waiting_cargo)
            prior_waiting = _waiting(previous.waiting_cargo)
            delta = waiting - prior_waiting
            if delta >= 1_000 and percentage_change(waiting, prior_waiting) >= 1:
                add_result(
                    findings,
                    recommendations,
                    _change_finding(
                        current=current,
                        comparison=comparison,
                        code="station_waiting_spike",
                        entity_type=AnalysisSubjectType.STATION,
                        entity_id=station.id,
                        field="waiting_cargo",
                        value=waiting,
                        previous=prior_waiting,
                        delta=delta,
                        title=f"Waiting cargo spike at {station.name}",
                        limitation="Waiting cargo alone does not establish congestion.",
                    ),
                )
        _route_anomalies(current, comparison, findings, recommendations)
        if not current.metadata.complete:
            add_result(findings, recommendations, _incomplete_snapshot(current, self.analysis_type))
        findings.sort(key=_priority_sort)
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer=f"Detected {len(findings)} bounded change anomalies.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=(
                "These are fixed change alerts, not statistical anomalies or learned baselines.",
            ),
        )


class EntitySummaryAnalyzer:
    analysis_type = AnalysisType.ENTITY_SUMMARY

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del comparison
        assert request.subject_type is not None
        collections = {
            AnalysisSubjectType.COMPANY: current.companies,
            AnalysisSubjectType.TOWN: current.towns,
            AnalysisSubjectType.INDUSTRY: current.industries,
            AnalysisSubjectType.STATION: current.stations,
            AnalysisSubjectType.VEHICLE: current.vehicles,
            AnalysisSubjectType.ROUTE: current.routes,
        }
        collection = collections[request.subject_type]
        values = [item for item in collection if item.id in request.subject_ids]
        findings: list[AnalysisFinding] = []
        for item in sorted(values, key=lambda value: value.id):
            payload = item.model_dump(mode="json")
            finding, _ = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code="entity_summary",
                entity_ids=(item.id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.INFORMATIONAL,
                title=f"{request.subject_type.value.title()} {item.id}",
                summary=f"Observed canonical summary for {item.id}.",
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    EvidenceReference(
                        source_type=EvidenceSourceType.SNAPSHOT_FIELD,
                        snapshot_id=current.metadata.snapshot_id,
                        entity_type=request.subject_type,
                        entity_id=item.id,
                        field="canonical_entity",
                        observed_value=payload,
                    ),
                ),
            )
            findings.append(finding)
        missing = sorted(set(request.subject_ids) - {item.id for item in values})
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED if findings else AnalysisStatus.INSUFFICIENT_DATA,
            answer=f"Found {len(findings)} of {len(request.subject_ids)} requested entities.",
            findings=tuple(findings),
            limitations=tuple(f"Entity {item} was not observed." for item in missing),
        )


class PriorityReviewAnalyzer:
    analysis_type = AnalysisType.PRIORITY_REVIEW

    _sources = (
        CompanyHealthAnalyzer(),
        VehiclePerformanceAnalyzer(),
        StationPerformanceAnalyzer(),
        RoutePerformanceAnalyzer(),
        TownCoverageAnalyzer(),
        IndustryOpportunitiesAnalyzer(),
    )
    _source_subjects = {
        AnalysisType.COMPANY_HEALTH: AnalysisSubjectType.COMPANY,
        AnalysisType.VEHICLE_PERFORMANCE: AnalysisSubjectType.VEHICLE,
        AnalysisType.STATION_PERFORMANCE: AnalysisSubjectType.STATION,
        AnalysisType.ROUTE_PERFORMANCE: AnalysisSubjectType.ROUTE,
        AnalysisType.TOWN_COVERAGE: AnalysisSubjectType.TOWN,
        AnalysisType.INDUSTRY_OPPORTUNITIES: AnalysisSubjectType.INDUSTRY,
    }

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        candidates: list[AnalysisFinding] = []
        limitations: list[str] = []
        for analyzer in self._sources:
            if request.subject_type not in {None, AnalysisSubjectType.WORLD} and (
                self._source_subjects[analyzer.analysis_type] is not request.subject_type
            ):
                continue
            source_request = AnalysisRequest(
                analysis_type=analyzer.analysis_type,
                question=request.question,
                comparison_snapshot_id=request.comparison_snapshot_id,
                maximum_findings=request.maximum_findings,
                include_recommendations=False,
            )
            result = analyzer.analyze(source_request, current, comparison)
            candidates.extend(result.findings)
            limitations.extend(result.limitations)
        candidates.sort(key=_priority_sort)
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        for source in candidates[: request.maximum_findings]:
            entity_ids = tuple(
                sorted({item.entity_id for item in source.evidence if item.entity_id is not None})
            )
            add_result(
                findings,
                recommendations,
                make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code=f"priority_{source.finding_code}",
                    entity_ids=entity_ids,
                    kind=source.kind,
                    severity=source.severity,
                    title=source.title,
                    summary=(
                        f"Priority score {priority_score(source.severity, source.confidence)}: "
                        f"{source.summary}"
                    ),
                    metric_name="priority_score",
                    metric_value=priority_score(source.severity, source.confidence),
                    confidence=source.confidence,
                    evidence=source.evidence,
                    limitations=source.limitations,
                    recommendation_code="inspect_priority_item",
                ),
            )
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer=f"Ranked {len(findings)} inspection targets from deterministic findings.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=tuple(dict.fromkeys(limitations)),
            population=AnalysisPopulation(
                eligible_count=len(candidates),
                evaluated_count=len(candidates),
                excluded_count=0,
                metric=RankingMetric.PRIORITY_SCORE,
                direction=RankingDirection.DESCENDING,
            ),
        )


def _change_finding(
    *,
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    code: str,
    entity_type: AnalysisSubjectType,
    entity_id: str,
    field: str,
    value: int,
    previous: int,
    delta: int,
    title: str,
    limitation: str,
) -> tuple[AnalysisFinding, AnalysisRecommendation | None]:
    return make_finding(
        snapshot=current,
        analysis_type=AnalysisType.ANOMALY_DETECTION,
        code=code,
        entity_ids=(entity_id,),
        kind=FindingKind.INFERRED_FINDING,
        severity=FindingSeverity.WARNING,
        title=title,
        summary=f"Observed value changed from {previous} to {value} (delta {delta}).",
        metric_name=field,
        metric_value=value,
        comparison_value=previous,
        confidence=EvidenceConfidence.MEDIUM,
        evidence=(
            field_evidence(
                current,
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
                value=value,
                comparison=comparison,
                comparison_value=previous,
            ),
        ),
        limitations=(limitation,),
        recommendation_code="inspect_anomalous_change",
    )


def _route_anomalies(
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    findings: list[AnalysisFinding],
    recommendations: list[AnalysisRecommendation],
) -> None:
    current_vehicles = {item.id: item for item in current.vehicles}
    previous_vehicles = {item.id: item for item in comparison.vehicles}
    previous_routes = {item.id: item for item in comparison.routes}
    for route in current.routes:
        previous = previous_routes.get(route.id)
        if previous is None:
            continue
        current_profit = sum(
            current_vehicles[item].profit_last_year
            for item in route.vehicle_ids
            if item in current_vehicles
        )
        previous_profit = sum(
            previous_vehicles[item].profit_last_year
            for item in previous.vehicle_ids
            if item in previous_vehicles
        )
        delta = current_profit - previous_profit
        if (
            delta < 0
            and percentage_change(current_profit, previous_profit) >= 0.5
            and abs(delta) >= 20_000
        ):
            add_result(
                findings,
                recommendations,
                _change_finding(
                    current=current,
                    comparison=comparison,
                    code="route_profit_drop",
                    entity_type=AnalysisSubjectType.ROUTE,
                    entity_id=route.id,
                    field="aggregate_profit_last_year",
                    value=current_profit,
                    previous=previous_profit,
                    delta=delta,
                    title=f"Large profit drop for route {route.id}",
                    limitation=ROUTE_COMPARISON_LIMITATION,
                ),
            )
        count_drop = len(previous.vehicle_ids) - len(route.vehicle_ids)
        if count_drop >= 2 and count_drop / max(len(previous.vehicle_ids), 1) >= 0.25:
            add_result(
                findings,
                recommendations,
                _change_finding(
                    current=current,
                    comparison=comparison,
                    code="route_vehicle_count_drop",
                    entity_type=AnalysisSubjectType.ROUTE,
                    entity_id=route.id,
                    field="vehicle_count",
                    value=len(route.vehicle_ids),
                    previous=len(previous.vehicle_ids),
                    delta=-count_drop,
                    title=f"Vehicle-count drop for route {route.id}",
                    limitation=ROUTE_COMPARISON_LIMITATION,
                ),
            )


def _incomplete_snapshot(
    current: WorldSnapshot, analysis_type: AnalysisType
) -> tuple[AnalysisFinding, AnalysisRecommendation | None]:
    return make_finding(
        snapshot=current,
        analysis_type=analysis_type,
        code="incomplete_snapshot",
        entity_ids=(),
        kind=FindingKind.DATA_QUALITY,
        severity=FindingSeverity.CRITICAL,
        title="Incomplete current snapshot",
        summary="The current snapshot reports incomplete collection.",
        confidence=EvidenceConfidence.HIGH,
        evidence=(
            EvidenceReference(
                source_type=EvidenceSourceType.CAPABILITY_COVERAGE,
                snapshot_id=current.metadata.snapshot_id,
                field="metadata.complete",
                observed_value=False,
            ),
        ),
        recommendation_code="inspect_snapshot_collection",
    )


def _waiting(flows: tuple[CargoFlow, ...]) -> int:
    return sum(item.waiting or 0 for item in flows)


def _field_change_severity(change: FieldChanged) -> FindingSeverity:
    if not isinstance(change.before, int) or not isinstance(change.after, int):
        return FindingSeverity.INFORMATIONAL
    delta = change.after - change.before
    if (
        change.field == "cash"
        and abs(delta) >= 100_000
        and percentage_change(change.after, change.before) >= 0.1
    ):
        return FindingSeverity.WARNING
    if (
        change.field == "loan"
        and delta > 0
        and delta >= 50_000
        and percentage_change(change.after, change.before) >= 0.1
    ):
        return FindingSeverity.WARNING
    if "profit" in change.field and change.before * change.after <= 0 and abs(delta) >= 10_000:
        return FindingSeverity.WARNING
    if (
        "waiting" in change.field
        and delta > 0
        and delta >= 500
        and percentage_change(change.after, change.before) >= 0.5
    ):
        return FindingSeverity.WARNING
    return FindingSeverity.INFORMATIONAL


def _subject(value: str) -> AnalysisSubjectType | None:
    try:
        return AnalysisSubjectType(value)
    except ValueError:
        return None


def _priority_sort(item: AnalysisFinding) -> tuple[int, str]:
    return -priority_score(item.severity, item.confidence), item.finding_id
