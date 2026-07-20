"""Deterministic, evidence-linked inspection guidance."""

from __future__ import annotations

from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnswerConcept,
    InspectionGuidance,
    InspectionGuidanceStatus,
    RankingMetric,
)
from sim_pilot.analysis.evidence_view import entity_display_labels
from sim_pilot.domain.world import WorldSnapshot


def inspection_guidance(
    request: AnalysisRequest,
    finding: AnalysisFinding | None,
    snapshot: WorldSnapshot,
    *,
    status: AnalysisStatus,
    unavailable_reason: str | None = None,
) -> InspectionGuidance:
    """Build one bounded inspection from the selected finding, or decline explicitly."""
    if finding is None or status in {
        AnalysisStatus.INSUFFICIENT_DATA,
        AnalysisStatus.CLARIFICATION_REQUIRED,
        AnalysisStatus.UNSUPPORTED,
        AnalysisStatus.FAILED,
    }:
        return _unavailable(
            unavailable_reason
            or "the current evidence does not identify a responsible, specific target"
        )

    intent = request.answer_intent
    code = finding.finding_code
    metric = finding.metric_name
    target_type, target_id, target_label = _target(finding, snapshot)

    if intent is not None and intent.concept in {
        AnswerConcept.AVAILABLE_CASH,
        AnswerConcept.DEBT,
    }:
        return _unavailable("this factual balance does not identify a problem or inspection target")

    if (
        intent is not None
        and intent.concept is AnswerConcept.HEALTH
        and (
            code == "operating_result"
            or (isinstance(finding.metric_value, int) and finding.metric_value >= 0)
        )
    ):
        return _unavailable("the current company evidence shows no urgent problem to inspect")

    if (
        intent is not None
        and intent.concept is AnswerConcept.LOSS
        and (isinstance(finding.metric_value, (int, float)) and finding.metric_value >= 0)
    ):
        return _unavailable(
            "the observed result corrects the loss premise and identifies no loss to inspect"
        )

    if metric == RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT.value:
        vehicle_type = _metric_input(finding, "vehicle_type")
        label = f"{vehicle_type.title()} vehicles" if vehicle_type else "the ranked vehicle type"
        return _recommended(
            finding,
            target_label=label,
            observation="compare member vehicles' orders, loading waits, and empty legs",
            diagnostic_value="one outlier vehicle from a type-wide operating pattern",
        )

    if target_label is None:
        return _unavailable(
            "the finding does not resolve to a named entity in the current snapshot"
        )

    if target_type is AnalysisSubjectType.VEHICLE:
        if "idle_vehicle" in code:
            observation = "check its current order, depot state, and whether service resumes"
            purpose = "an intentional hold from interrupted or obsolete service"
        elif metric in {"profit_last_year", "profit_this_year"} or "profit" in code:
            observation = "compare its orders, loading waits, and empty return legs"
            purpose = "low demand from inefficient orders or repeated empty running"
        else:
            observation = "compare its current orders, running state, and assigned route"
            purpose = "an isolated vehicle issue from a route-level pattern"
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation=observation,
            diagnostic_value=purpose,
        )

    if target_type is AnalysisSubjectType.STATION or metric == RankingMetric.WAITING_CARGO.value:
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation="compare vehicle frequency, waiting cargo types, and route destinations",
            diagnostic_value="insufficient service from cargo the current routes do not accept",
        )

    if target_type is AnalysisSubjectType.ROUTE or metric in {
        RankingMetric.ROUTE_AGGREGATE_PROFIT.value,
        RankingMetric.ROUTE_NEGATIVE_VEHICLE_COUNT.value,
    }:
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation="compare member vehicles' profits, orders, loading waits, and empty legs",
            diagnostic_value="one weak vehicle from a route-wide operating pattern",
        )

    if target_type is AnalysisSubjectType.INDUSTRY:
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation=(
                "check produced cargo, possible destinations, and nearby station catchments"
            ),
            diagnostic_value=(
                "an observable service gap from a connection the current evidence cannot assess"
            ),
        )

    if target_type is AnalysisSubjectType.TOWN:
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation=(
                "check passenger and mail demand, nearby stations, and reachable destinations"
            ),
            diagnostic_value="an observable service gap from proximity without useful demand",
        )

    if target_type is AnalysisSubjectType.COMPANY and (
        metric == "net_operating_result" or "operating_result" in code
    ):
        return _recommended(
            finding,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            observation="compare losing vehicles, high-waiting stations, and route results",
            diagnostic_value="a localized service problem from a company-wide shortfall",
        )

    return _recommended(
        finding,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        observation="compare the cited metric with its orders, service state, or prior snapshot",
        diagnostic_value="a transient observation from a persistent operating issue",
    )


def render_inspection_guidance(guidance: InspectionGuidance) -> str:
    if guidance.status is InspectionGuidanceStatus.NOT_RESPONSIBLE:
        return (
            "No responsible next inspection can be recommended because "
            f"{guidance.unavailable_reason}."
        )
    return (
        f"Inspect {guidance.target_label}: {guidance.observation}. "
        f"This will help distinguish {guidance.diagnostic_value}."
    )


def _target(
    finding: AnalysisFinding, snapshot: WorldSnapshot
) -> tuple[AnalysisSubjectType | None, str | None, str | None]:
    for evidence in finding.evidence:
        if evidence.entity_type is None or evidence.entity_id is None:
            continue
        labels = entity_display_labels(snapshot, evidence.entity_type)
        return evidence.entity_type, evidence.entity_id, labels.get(evidence.entity_id)
    return None, None, None


def _metric_input(finding: AnalysisFinding, name: str) -> str | None:
    for evidence in finding.evidence:
        value = evidence.metric_inputs.get(name)
        if isinstance(value, str):
            return value
    return None


def _recommended(
    finding: AnalysisFinding,
    *,
    target_label: str,
    observation: str,
    diagnostic_value: str,
    target_type: AnalysisSubjectType | None = None,
    target_id: str | None = None,
) -> InspectionGuidance:
    return InspectionGuidance(
        status=InspectionGuidanceStatus.RECOMMENDED,
        target_entity_type=target_type,
        target_entity_id=target_id,
        target_label=target_label,
        observation=observation,
        diagnostic_value=diagnostic_value,
        supporting_finding_ids=(finding.finding_id,),
    )


def _unavailable(reason: str) -> InspectionGuidance:
    return InspectionGuidance(
        status=InspectionGuidanceStatus.NOT_RESPONSIBLE,
        unavailable_reason=reason,
    )
