"""Stable evidence identities and canonical snapshot lookup helpers."""

from __future__ import annotations

import hashlib

from sim_pilot.analysis.contracts import (
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    EvidenceReference,
    EvidenceSourceType,
)
from sim_pilot.analysis.errors import AnalysisInputError
from sim_pilot.domain.models import JsonValue
from sim_pilot.domain.world import Company, CoverageStatus, WorldSnapshot


def stable_finding_id(
    analysis_type: AnalysisType,
    snapshot_id: str,
    finding_code: str,
    entity_ids: tuple[str, ...] = (),
) -> str:
    material = "|".join((analysis_type.value, snapshot_id, finding_code, *sorted(entity_ids)))
    return f"finding:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def stable_recommendation_id(snapshot_id: str, code: str, finding_ids: tuple[str, ...]) -> str:
    material = "|".join((snapshot_id, code, *sorted(finding_ids)))
    return f"recommendation:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def field_evidence(
    snapshot: WorldSnapshot,
    *,
    entity_type: AnalysisSubjectType,
    entity_id: str,
    field: str,
    value: JsonValue,
    comparison: WorldSnapshot | None = None,
    comparison_value: JsonValue = None,
) -> EvidenceReference:
    return EvidenceReference(
        source_type=EvidenceSourceType.SNAPSHOT_FIELD,
        snapshot_id=snapshot.metadata.snapshot_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        observed_value=value,
        comparison_snapshot_id=(None if comparison is None else comparison.metadata.snapshot_id),
        comparison_value=comparison_value,
    )


def metric_evidence(
    snapshot: WorldSnapshot,
    *,
    field: str,
    value: JsonValue,
    inputs: dict[str, JsonValue],
    entity_type: AnalysisSubjectType | None = None,
    entity_id: str | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        source_type=EvidenceSourceType.DERIVED_METRIC,
        snapshot_id=snapshot.metadata.snapshot_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        observed_value=value,
        metric_inputs=inputs,
    )


def observer_company(snapshot: WorldSnapshot) -> Company:
    identifier = snapshot.metadata.observer_company_id
    if identifier is None:
        if len(snapshot.companies) == 1:
            return snapshot.companies[0]
        raise AnalysisInputError("observer company is unavailable or ambiguous")
    company = next((item for item in snapshot.companies if item.id == identifier), None)
    if company is None:
        raise AnalysisInputError("observer company is absent from the company collection")
    return company


def evidence_confidence(
    snapshot: WorldSnapshot, *, category: str, inferred: bool = False
) -> EvidenceConfidence:
    if not snapshot.metadata.complete:
        return EvidenceConfidence.LOW
    status = next((item.status for item in snapshot.coverage if item.category == category), None)
    if status is CoverageStatus.UNAVAILABLE or status is None:
        return EvidenceConfidence.LOW
    return EvidenceConfidence.MEDIUM if inferred else EvidenceConfidence.HIGH
