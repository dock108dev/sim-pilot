"""Deterministic question-first composition over authoritative analyzer output."""

from __future__ import annotations

from typing import Protocol

from sim_pilot.analysis.analyzers.support import filter_value
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisPresentation,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    AnswerBasis,
    AnswerConcept,
    EvidenceSourceType,
    FindingKind,
    FindingSeverity,
    RankingMetric,
)
from sim_pilot.domain.models import JsonValue
from sim_pilot.domain.world import Vehicle, WorldSnapshot

_RANKING_METRICS: dict[RankingMetric, str] = {
    RankingMetric.CASH: "cash",
    RankingMetric.LOAN: "loan",
    RankingMetric.COMPANY_VALUE: "company_value",
    RankingMetric.INCOME: "income",
    RankingMetric.EXPENSES: "expenses",
    RankingMetric.NET_OPERATING_RESULT: "net_operating_result",
    RankingMetric.PROFIT_THIS_YEAR: "profit_this_year",
    RankingMetric.PROFIT_LAST_YEAR: "profit_last_year",
    RankingMetric.AGE_DAYS: "age_days",
    RankingMetric.RUNNING_STATE: "running_state",
    RankingMetric.WAITING_CARGO: "waiting_cargo",
    RankingMetric.VEHICLE_COUNT: "vehicle_count",
    RankingMetric.CARGO_PER_VEHICLE: "cargo_per_vehicle",
    RankingMetric.CARGO_TYPE_COVERAGE: "cargo_type_coverage",
    RankingMetric.NEGATIVE_PROFIT_VEHICLE_COUNT: "negative_profit_vehicle_count",
    RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT: "vehicle_type_aggregate_profit",
    RankingMetric.ROUTE_AGGREGATE_PROFIT: "route_aggregate_profit",
    RankingMetric.ROUTE_MEDIAN_PROFIT: "route_median_profit",
    RankingMetric.ROUTE_NEGATIVE_VEHICLE_COUNT: "route_negative_vehicle_count",
    RankingMetric.POPULATION: "population",
    RankingMetric.PRODUCTION: "production",
    RankingMetric.OPPORTUNITY_SCORE: "opportunity_score",
    RankingMetric.PRIORITY_SCORE: "priority_score",
    RankingMetric.MATERIALITY: "materiality",
}


class _HasID(Protocol):
    id: str


def compose_interaction(
    request: AnalysisRequest,
    *,
    snapshot: WorldSnapshot,
    comparison: WorldSnapshot | None,
    status: AnalysisStatus,
    findings: tuple[AnalysisFinding, ...],
    recommendations: tuple[AnalysisRecommendation, ...],
    limitations: tuple[str, ...],
    fallback_answer: str,
) -> tuple[AnalysisStatus, str, AnalysisPresentation]:
    """Select one exact answer without changing or manufacturing analyzer evidence."""
    intent = request.answer_intent
    required_metric = _required_metric(request)

    if intent is not None and intent.comparison_required:
        comparison_problem = _comparison_problem(request, comparison, findings)
        if comparison_problem is not None:
            direct = f"Insufficient data: {comparison_problem}"
            return (
                AnalysisStatus.INSUFFICIENT_DATA,
                direct,
                AnalysisPresentation(
                    direct_answer=direct,
                    basis=AnswerBasis.INSUFFICIENT_DATA,
                    limitation=(
                        "A compatible snapshot pair is not evidence that a change was evaluated."
                    ),
                    follow_up=(
                        "Select or collect a compatible comparison snapshot with typed changes."
                    ),
                    evaluated_count=0,
                    excluded_count=0,
                ),
            )

    decisive = _select_decisive(request, findings, required_metric, snapshot)
    if intent is not None and intent.concept is AnswerConcept.IDLE and decisive is None:
        direct = "No idle vehicles were detected in the observed company fleet."
        return (
            status,
            direct,
            AnalysisPresentation(
                direct_answer=direct,
                basis=AnswerBasis.CONFIRMED_FACT,
                limitation=(
                    "Idle means a vehicle was observed in a depot or with running state "
                    "idle or stopped."
                ),
                evaluated_count=_owned_vehicle_count(snapshot),
                excluded_count=0,
            ),
        )

    if required_metric is not None and decisive is None:
        direct = (
            f"Insufficient data: no evaluated finding matches the requested "
            f"{required_metric.replace('_', ' ')} metric."
        )
        evaluated, excluded = _ranking_counts(request, snapshot)
        return (
            AnalysisStatus.INSUFFICIENT_DATA,
            direct,
            AnalysisPresentation(
                direct_answer=direct,
                basis=AnswerBasis.INSUFFICIENT_DATA,
                limitation="A nearby metric was not substituted for the requested metric.",
                follow_up="Choose a supported metric or collect the missing evidence.",
                evaluated_count=evaluated,
                excluded_count=excluded,
            ),
        )

    if decisive is None:
        basis = (
            AnswerBasis.INSUFFICIENT_DATA
            if status is AnalysisStatus.INSUFFICIENT_DATA
            else AnswerBasis.FINDING
        )
        direct = (
            "Insufficient data: the snapshot did not contain enough supported evidence to "
            "answer this question."
            if status is AnalysisStatus.INSUFFICIENT_DATA
            else fallback_answer
        )
        return (
            status,
            direct,
            AnalysisPresentation(
                direct_answer=direct,
                basis=basis,
                limitation=limitations[0] if limitations else None,
            ),
        )

    direct = _direct_answer(request, decisive)
    recommendation = _supported_recommendation(decisive, recommendations)
    limitation = _material_limitation(request, decisive, limitations)
    evaluated, excluded = _ranking_counts(request, snapshot)
    return (
        status,
        direct,
        AnalysisPresentation(
            direct_answer=direct,
            basis=(
                AnswerBasis.CONFIRMED_FACT
                if decisive.kind is FindingKind.OBSERVED_FACT
                else AnswerBasis.INFERENCE
            ),
            decisive_finding_id=decisive.finding_id,
            recommendation_id=(
                None if recommendation is None else recommendation.recommendation_id
            ),
            limitation=limitation,
            follow_up=_follow_up(request, decisive),
            evaluated_count=evaluated,
            excluded_count=excluded,
        ),
    )


def _required_metric(request: AnalysisRequest) -> str | None:
    intent = request.answer_intent
    if intent is not None and intent.requested_metric is not None:
        return intent.requested_metric.value
    if request.ranking is not None:
        return _RANKING_METRICS[request.ranking.metric]
    return None


def _comparison_problem(
    request: AnalysisRequest,
    comparison: WorldSnapshot | None,
    findings: tuple[AnalysisFinding, ...],
) -> str | None:
    if comparison is None or request.comparison_snapshot_id is None:
        return "the requested comparison snapshot was not supplied."
    comparison_id = comparison.metadata.snapshot_id
    if request.comparison_snapshot_id != comparison_id:
        return "the supplied comparison identity does not match the request."
    change_evidence = tuple(
        evidence
        for finding in findings
        for evidence in finding.evidence
        if evidence.source_type is EvidenceSourceType.SNAPSHOT_CHANGE
        and evidence.comparison_snapshot_id == comparison_id
    )
    if not change_evidence:
        return "the compatible snapshots contain no evaluated typed change evidence."
    return None


def _select_decisive(
    request: AnalysisRequest,
    findings: tuple[AnalysisFinding, ...],
    required_metric: str | None,
    snapshot: WorldSnapshot,
) -> AnalysisFinding | None:
    intent = request.answer_intent
    if intent is not None and intent.concept is AnswerConcept.IDLE:
        return next((item for item in findings if item.finding_code == "idle_vehicle"), None)
    candidates = (
        findings
        if required_metric is None
        else tuple(item for item in findings if item.metric_name == required_metric)
    )
    if not candidates:
        return None
    if required_metric is not None:
        candidate = candidates[0]
        if request.ranking is not None and not _matches_actual_ranking_top(
            request, snapshot, candidate, required_metric
        ):
            return None
        return candidate
    operating = next(
        (item for item in candidates if item.metric_name == "net_operating_result"), None
    )
    if intent is not None and intent.concept is AnswerConcept.HEALTH and operating is not None:
        return operating
    return min(candidates, key=lambda item: (-_severity(item.severity), item.finding_id))


def _direct_answer(request: AnalysisRequest, finding: AnalysisFinding) -> str:
    intent = request.answer_intent
    concept = None if intent is None else intent.concept
    value = finding.metric_value
    if concept is AnswerConcept.LOSS and finding.metric_name == "net_operating_result":
        if isinstance(value, (int, float)) and value >= 0:
            return (
                "You are not losing money at company level in the observed accounting period; "
                f"income plus expenses is {_currency(value)}."
            )
        return (
            "The company is losing money at company level in the observed accounting period; "
            f"income plus expenses is {_currency(value)}."
        )
    if concept is AnswerConcept.HEALTH and finding.metric_name == "net_operating_result":
        direction = "positive" if isinstance(value, (int, float)) and value >= 0 else "negative"
        return (
            f"The observed company-level operating result is {direction} at {_currency(value)}; "
            "this is a financial health signal, not a complete company-health verdict."
        )
    if concept is AnswerConcept.DEBT and finding.metric_name == "loan":
        if value == 0:
            return "There is no observed outstanding company loan."
        return (
            f"The observed company loan is {_currency(value)}; whether that is too much requires "
            "company-value or repayment context."
        )
    if concept is AnswerConcept.AVAILABLE_CASH and finding.metric_name == "cash":
        return (
            f"The observed company cash balance available in this snapshot is {_currency(value)}."
        )
    if concept is AnswerConcept.CHANGE:
        return f"The most material evaluated change is: {finding.summary}"
    if concept is AnswerConcept.IDLE:
        return f"At least one idle vehicle was detected: {finding.title}."
    if request.ranking is not None:
        metric_label = (finding.metric_name or "requested metric").replace("_", " ")
        return f"The top result by {metric_label} is {finding.title}."
    return finding.summary


def _supported_recommendation(
    finding: AnalysisFinding,
    recommendations: tuple[AnalysisRecommendation, ...],
) -> AnalysisRecommendation | None:
    supported = [
        item
        for item in recommendations
        if finding.finding_id in item.supporting_finding_ids
        and item.recommendation_id in finding.recommendation_ids
    ]
    return min(supported, key=lambda item: (item.priority, item.recommendation_id), default=None)


def _material_limitation(
    request: AnalysisRequest,
    finding: AnalysisFinding,
    limitations: tuple[str, ...],
) -> str | None:
    intent = request.answer_intent
    if intent is not None and intent.concept is AnswerConcept.AVAILABLE_CASH:
        return "The snapshot does not expose committed future costs or infrastructure liabilities."
    if intent is not None and intent.concept is AnswerConcept.DEBT:
        return "The snapshot does not expose loan terms or repayment burden."
    values = (*finding.limitations, *limitations)
    return next(iter(dict.fromkeys(values)), None)


def _follow_up(request: AnalysisRequest, finding: AnalysisFinding) -> str | None:
    intent = request.answer_intent
    if intent is not None and intent.concept is AnswerConcept.LOSS:
        return "Ask which vehicles lost the most money last year to inspect local losses."
    if intent is not None and intent.concept is AnswerConcept.CHANGE:
        return "Inspect the evidence for this change before acting on it."
    if request.ranking is not None:
        return f"Inspect the evidence for {finding.title}."
    return None


def _ranking_counts(
    request: AnalysisRequest, snapshot: WorldSnapshot
) -> tuple[int | None, int | None]:
    if request.ranking is None:
        return None, None
    subject = request.subject_type or _default_subject(request.analysis_type)
    if subject is AnalysisSubjectType.VEHICLE:
        company_id = snapshot.metadata.observer_company_id
        values = [item for item in snapshot.vehicles if item.owner_id == company_id]
        selected: list[Vehicle] = []
        for item in values:
            fields: dict[str, object] = {
                "entity_id": item.id,
                "owner_id": item.owner_id,
                "vehicle_type": item.type,
                "route_id": item.route_id,
                "running_state": item.running_state,
                "in_depot": item.in_depot,
                "profit_this_year": item.profit_this_year,
                "profit_last_year": item.profit_last_year,
                "age_days": item.age_days,
            }
            if request.subject_ids and item.id not in request.subject_ids:
                continue
            if all(filter_value(request.filters, field, value) for field, value in fields.items()):
                selected.append(item)
        metric = _required_metric(request)
        missing = sum(_vehicle_metric(item, metric) is None for item in selected)
        return len(selected) - missing, missing
    if subject is AnalysisSubjectType.COMPANY:
        return _selected_count(snapshot.companies, request.subject_ids), 0
    if subject is AnalysisSubjectType.STATION:
        return _selected_count(snapshot.stations, request.subject_ids), 0
    if subject is AnalysisSubjectType.ROUTE:
        return _selected_count(snapshot.routes, request.subject_ids), 0
    if subject is AnalysisSubjectType.TOWN:
        return _selected_count(snapshot.towns, request.subject_ids), 0
    if subject is AnalysisSubjectType.INDUSTRY:
        return _selected_count(snapshot.industries, request.subject_ids), 0
    return 0, 0


def _matches_actual_ranking_top(
    request: AnalysisRequest,
    snapshot: WorldSnapshot,
    candidate: AnalysisFinding,
    metric: str,
) -> bool:
    if request.analysis_type is not AnalysisType.VEHICLE_PERFORMANCE:
        return True
    company_id = snapshot.metadata.observer_company_id
    vehicles: list[Vehicle] = []
    for item in snapshot.vehicles:
        if item.owner_id != company_id:
            continue
        fields: dict[str, object] = {
            "entity_id": item.id,
            "owner_id": item.owner_id,
            "vehicle_type": item.type,
            "route_id": item.route_id,
            "running_state": item.running_state,
            "in_depot": item.in_depot,
            "profit_this_year": item.profit_this_year,
            "profit_last_year": item.profit_last_year,
            "age_days": item.age_days,
        }
        if request.subject_ids and item.id not in request.subject_ids:
            continue
        if all(filter_value(request.filters, field, value) for field, value in fields.items()):
            vehicles.append(item)
    ranked = [item for item in vehicles if _vehicle_metric(item, metric) is not None]
    if not ranked or request.ranking is None:
        return False
    reverse = request.ranking.direction.value == "descending"
    ranked.sort(
        key=lambda item: (
            -float(_vehicle_metric(item, metric) or 0)
            if reverse
            else float(_vehicle_metric(item, metric) or 0),
            item.id,
        )
    )
    candidate_ids = {
        evidence.entity_id
        for evidence in candidate.evidence
        if evidence.entity_type is AnalysisSubjectType.VEHICLE
    }
    return ranked[0].id in candidate_ids


def _selected_count(values: tuple[_HasID, ...], subject_ids: tuple[str, ...]) -> int:
    if not subject_ids:
        return len(values)
    return sum(item.id in subject_ids for item in values)


def _vehicle_metric(vehicle: Vehicle, metric: str | None) -> int | None:
    if metric == "profit_this_year":
        return vehicle.profit_this_year
    if metric == "profit_last_year":
        return vehicle.profit_last_year
    if metric == "age_days":
        return vehicle.age_days
    return None


def _default_subject(analysis_type: AnalysisType) -> AnalysisSubjectType | None:
    return {
        AnalysisType.VEHICLE_PERFORMANCE: AnalysisSubjectType.VEHICLE,
        AnalysisType.STATION_PERFORMANCE: AnalysisSubjectType.STATION,
        AnalysisType.ROUTE_PERFORMANCE: AnalysisSubjectType.ROUTE,
        AnalysisType.TOWN_COVERAGE: AnalysisSubjectType.TOWN,
        AnalysisType.INDUSTRY_OPPORTUNITIES: AnalysisSubjectType.INDUSTRY,
    }.get(analysis_type)


def _owned_vehicle_count(snapshot: WorldSnapshot) -> int:
    company_id = snapshot.metadata.observer_company_id
    return sum(item.owner_id == company_id for item in snapshot.vehicles)


def _severity(value: FindingSeverity) -> int:
    return {
        FindingSeverity.INFORMATIONAL: 0,
        FindingSeverity.OPPORTUNITY: 1,
        FindingSeverity.WARNING: 2,
        FindingSeverity.CRITICAL: 3,
    }[value]


def _currency(value: JsonValue) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"£{value:,.0f}"
