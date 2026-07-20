"""Shared deterministic analyzer helpers."""

from __future__ import annotations

from collections.abc import Iterable

from sim_pilot.analysis.contracts import (
    AnalysisFilter,
    AnalysisFilterOperator,
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    EvidenceReference,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.analysis.evidence import stable_finding_id, stable_recommendation_id
from sim_pilot.domain.models import JsonValue
from sim_pilot.domain.world import WorldSnapshot

SEVERITY_BASE = {
    FindingSeverity.INFORMATIONAL: 0,
    FindingSeverity.OPPORTUNITY: 25,
    FindingSeverity.WARNING: 50,
    FindingSeverity.CRITICAL: 75,
}
CONFIDENCE_POINTS = {
    EvidenceConfidence.LOW: 5,
    EvidenceConfidence.MEDIUM: 15,
    EvidenceConfidence.HIGH: 25,
}


def priority_score(severity: FindingSeverity, confidence: EvidenceConfidence) -> int:
    return SEVERITY_BASE[severity] + CONFIDENCE_POINTS[confidence]


def percentage_change(current: int, previous: int) -> float:
    return abs(current - previous) / max(abs(previous), 1)


def make_finding(
    *,
    snapshot: WorldSnapshot,
    analysis_type: AnalysisType,
    code: str,
    entity_ids: tuple[str, ...],
    kind: FindingKind,
    severity: FindingSeverity,
    title: str,
    summary: str,
    confidence: EvidenceConfidence,
    evidence: tuple[EvidenceReference, ...],
    metric_name: str | None = None,
    metric_value: JsonValue = None,
    comparison_value: JsonValue = None,
    limitations: tuple[str, ...] = (),
    recommendation_code: str | None = None,
) -> tuple[AnalysisFinding, AnalysisRecommendation | None]:
    finding_id = stable_finding_id(analysis_type, snapshot.metadata.snapshot_id, code, entity_ids)
    recommendation: AnalysisRecommendation | None = None
    recommendation_ids: tuple[str, ...] = ()
    if recommendation_code is not None:
        recommendation_id = stable_recommendation_id(
            snapshot.metadata.snapshot_id, recommendation_code, (finding_id,)
        )
        recommendation_ids = (recommendation_id,)
        recommendation = AnalysisRecommendation(
            recommendation_id=recommendation_id,
            title=f"Inspect {title.lower()}",
            rationale=summary,
            priority=priority_score(severity, confidence),
            affected_entity_ids=entity_ids,
            supporting_finding_ids=(finding_id,),
            limitations=limitations,
        )
    return (
        AnalysisFinding(
            finding_id=finding_id,
            finding_code=code,
            analysis_type=analysis_type,
            kind=kind,
            severity=severity,
            title=title,
            summary=summary,
            metric_name=metric_name,
            metric_value=metric_value,
            comparison_value=comparison_value,
            confidence=confidence,
            evidence=evidence,
            limitations=limitations,
            recommendation_ids=recommendation_ids,
        ),
        recommendation,
    )


def add_result(
    findings: list[AnalysisFinding],
    recommendations: list[AnalysisRecommendation],
    result: tuple[AnalysisFinding, AnalysisRecommendation | None],
) -> None:
    finding, recommendation = result
    findings.append(finding)
    if recommendation is not None:
        recommendations.append(recommendation)


def requested_ids(request: AnalysisRequest, subject: AnalysisSubjectType) -> frozenset[str] | None:
    if request.subject_type is subject and request.subject_ids:
        return frozenset(request.subject_ids)
    return None


def filter_value(filters: Iterable[AnalysisFilter], field: str, value: object) -> bool:
    for item in filters:
        if item.field.value != field:
            continue
        candidate = item.values[0]
        if item.operator is AnalysisFilterOperator.EQUAL and value != candidate:
            return False
        if item.operator is AnalysisFilterOperator.NOT_EQUAL and value == candidate:
            return False
        if item.operator is AnalysisFilterOperator.IN and value not in item.values:
            return False
        if item.operator is AnalysisFilterOperator.LESS_THAN and not _compare(
            value, candidate, "lt"
        ):
            return False
        if item.operator is AnalysisFilterOperator.LESS_THAN_OR_EQUAL and not _compare(
            value, candidate, "le"
        ):
            return False
        if item.operator is AnalysisFilterOperator.GREATER_THAN and not _compare(
            value, candidate, "gt"
        ):
            return False
        if item.operator is AnalysisFilterOperator.GREATER_THAN_OR_EQUAL and not _compare(
            value, candidate, "ge"
        ):
            return False
    return True


def _compare(value: object, candidate: object, operator: str) -> bool:
    if not isinstance(value, int) or not isinstance(candidate, int):
        return False
    if operator == "lt":
        return value < candidate
    if operator == "le":
        return value <= candidate
    if operator == "gt":
        return value > candidate
    return value >= candidate
