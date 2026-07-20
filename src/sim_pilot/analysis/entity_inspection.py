"""Fail-closed boundary for explicitly requested OpenTTD entity inspection."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.contracts import AnalysisSubjectType
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.domain.world import WorldSnapshot


class EntityInspectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class InspectionEntityKind(StrEnum):
    VEHICLE = "vehicle"
    STATION = "station"
    TOWN = "town"
    INDUSTRY = "industry"


class InspectionIntent(StrEnum):
    FOCUS_NAMED_ENTITY = "focus_named_entity"


class InspectionResultStatus(StrEnum):
    UNSUPPORTED = "unsupported"


class InspectionEvidenceKind(StrEnum):
    RETAINED_REFERENCE = "retained_reference"
    LIVE_IDENTITY = "live_identity"
    LIVE_ENTITY = "live_entity"
    CAPABILITY_NEGOTIATION = "capability_negotiation"
    VERIFICATION_BOUNDARY = "verification_boundary"


class InspectionSnapshotIdentity(EntityInspectionModel):
    snapshot_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    save_generation: int = Field(ge=0)
    capability_fingerprint: str = Field(min_length=1)
    observer_company_id: str = Field(min_length=1)
    bridge_company_context: int = Field(ge=0, le=14)

    @classmethod
    def from_snapshot(
        cls, snapshot: WorldSnapshot, *, bridge_company_context: int
    ) -> InspectionSnapshotIdentity:
        metadata = snapshot.metadata
        if metadata.observer_company_id is None:
            raise EntityInspectionError(
                "missing_identity", "retained snapshot has no observer company identity"
            )
        return cls(
            snapshot_id=metadata.snapshot_id,
            world_id=metadata.world_id,
            save_generation=metadata.save_generation,
            capability_fingerprint=metadata.capability_fingerprint,
            observer_company_id=metadata.observer_company_id,
            bridge_company_context=bridge_company_context,
        )


class EntityInspectionAction(EntityInspectionModel):
    action_id: str = Field(pattern=r"^inspection:[0-9a-f]{20}$")
    analysis_id: str = Field(pattern=r"^analysis:[0-9a-f]{20}$")
    finding_id: str = Field(min_length=1)
    entity_kind: InspectionEntityKind
    canonical_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    snapshot_identity: InspectionSnapshotIdentity
    intent: InspectionIntent = InspectionIntent.FOCUS_NAMED_ENTITY


class InspectionVerificationEvidence(EntityInspectionModel):
    kind: InspectionEvidenceKind
    passed: bool
    detail: str = Field(min_length=1)


class EntityInspectionResult(EntityInspectionModel):
    action: EntityInspectionAction
    status: InspectionResultStatus
    reason_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    executed: Literal[False] = False
    economic_mutation: Literal[False] = False
    verification_evidence: tuple[InspectionVerificationEvidence, ...] = Field(min_length=1)


class EntityInspectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_KINDS = {
    AnalysisSubjectType.VEHICLE: InspectionEntityKind.VEHICLE,
    AnalysisSubjectType.STATION: InspectionEntityKind.STATION,
    AnalysisSubjectType.TOWN: InspectionEntityKind.TOWN,
    AnalysisSubjectType.INDUSTRY: InspectionEntityKind.INDUSTRY,
}


def resolve_inspection_action(
    record: AnalysisSessionRecord, finding_id: str
) -> EntityInspectionAction:
    finding = next(
        (item for item in record.response.findings if item.finding_id == finding_id), None
    )
    if finding is None:
        raise EntityInspectionError("missing_finding", f"finding {finding_id!r} was not found")

    candidates: set[tuple[InspectionEntityKind, str]] = set()
    presentation = record.response.presentation
    if presentation is not None:
        guidance = presentation.inspection_guidance
        subject = guidance.target_entity_type
        entity_kind = None if subject is None else _KINDS.get(subject)
        if (
            guidance.target_entity_id is not None
            and entity_kind is not None
            and finding_id in guidance.supporting_finding_ids
        ):
            candidates.add((entity_kind, guidance.target_entity_id))
    if not candidates:
        for item in finding.evidence:
            entity_kind = None if item.entity_type is None else _KINDS.get(item.entity_type)
            if entity_kind is not None and item.entity_id is not None:
                candidates.add((entity_kind, item.entity_id))
    if not candidates:
        raise EntityInspectionError(
            "unsupported_entity_kind",
            "finding does not identify one inspectable vehicle, station, town, or industry",
        )
    if len(candidates) != 1:
        raise EntityInspectionError(
            "ambiguous_entity", "finding identifies more than one inspectable entity"
        )
    entity_kind, canonical_id = next(iter(candidates))
    entity = _find_entity(record.snapshot, entity_kind, canonical_id)
    if entity is None:
        raise EntityInspectionError(
            "missing_entity", "finding entity is absent from its retained snapshot"
        )
    bridge_context = record.response.snapshot_metadata.bridge_company_context
    if bridge_context is None:
        raise EntityInspectionError(
            "missing_identity", "retained analysis has no verified bridge company context"
        )
    identity = InspectionSnapshotIdentity.from_snapshot(
        record.snapshot, bridge_company_context=bridge_context
    )
    material = "|".join(
        (
            record.analysis_id,
            finding_id,
            entity_kind.value,
            canonical_id,
            identity.world_id,
            str(identity.save_generation),
            InspectionIntent.FOCUS_NAMED_ENTITY.value,
        )
    )
    return EntityInspectionAction(
        action_id=f"inspection:{hashlib.sha256(material.encode()).hexdigest()[:20]}",
        analysis_id=record.analysis_id,
        finding_id=finding_id,
        entity_kind=entity_kind,
        canonical_id=canonical_id,
        target_label=getattr(entity, "name", canonical_id),
        snapshot_identity=identity,
    )


def evaluate_unsupported_inspection(
    action: EntityInspectionAction,
    current: WorldSnapshot,
    *,
    bridge_company_context: int,
    supported_actions: tuple[str, ...],
) -> EntityInspectionResult:
    retained = action.snapshot_identity
    current_identity = InspectionSnapshotIdentity.from_snapshot(
        current, bridge_company_context=bridge_company_context
    )
    if retained.world_id != current_identity.world_id:
        raise EntityInspectionError(
            "wrong_world", "retained finding belongs to a different OpenTTD world"
        )
    compatible = (
        retained.save_generation == current_identity.save_generation
        and retained.capability_fingerprint == current_identity.capability_fingerprint
        and retained.observer_company_id == current_identity.observer_company_id
        and retained.bridge_company_context == current_identity.bridge_company_context
    )
    if not compatible:
        raise EntityInspectionError(
            "stale_reference",
            "retained finding no longer matches the live save, company, or bridge capabilities",
        )
    if _find_entity(current, action.entity_kind, action.canonical_id) is None:
        raise EntityInspectionError(
            "stale_reference", "named entity is absent from a fresh compatible snapshot"
        )
    advertised = "focus_named_entity" in supported_actions
    capability_detail = (
        "bridge unexpectedly advertises focus_named_entity, but this build has no live-proven "
        "verification contract"
        if advertised
        else "bridge does not advertise focus_named_entity; advertised actions: "
        + (", ".join(supported_actions) or "none")
    )
    return EntityInspectionResult(
        action=action,
        status=InspectionResultStatus.UNSUPPORTED,
        reason_code="no_verifiable_inspection_capability",
        message=(
            f"OpenTTD inspection is unsupported for {action.target_label}. The supported "
            "interfaces cannot verify that a client opened or focused the named entity."
        ),
        verification_evidence=(
            InspectionVerificationEvidence(
                kind=InspectionEvidenceKind.RETAINED_REFERENCE,
                passed=True,
                detail="finding resolves to one retained canonical entity",
            ),
            InspectionVerificationEvidence(
                kind=InspectionEvidenceKind.LIVE_IDENTITY,
                passed=True,
                detail="fresh snapshot matches world, save generation, company, and capabilities",
            ),
            InspectionVerificationEvidence(
                kind=InspectionEvidenceKind.LIVE_ENTITY,
                passed=True,
                detail="named canonical entity remains present in the fresh snapshot",
            ),
            InspectionVerificationEvidence(
                kind=InspectionEvidenceKind.CAPABILITY_NEGOTIATION,
                passed=advertised,
                detail=capability_detail,
            ),
            InspectionVerificationEvidence(
                kind=InspectionEvidenceKind.VERIFICATION_BOUNDARY,
                passed=False,
                detail="Admin and GameScript APIs expose no readable client viewport postcondition",
            ),
        ),
    )


def render_inspection_result(result: EntityInspectionResult) -> str:
    lines = [
        f"Unsupported: {result.action.target_label}",
        result.message,
        "",
        "Verification evidence",
    ]
    lines.extend(
        f"- {'passed' if item.passed else 'not proven'}: {item.detail}"
        for item in result.verification_evidence
    )
    lines.extend(("", "No OpenTTD action was executed; economic state was not mutated."))
    return "\n".join(lines)


def _find_entity(
    snapshot: WorldSnapshot, entity_kind: InspectionEntityKind, canonical_id: str
) -> object | None:
    collections = {
        InspectionEntityKind.VEHICLE: snapshot.vehicles,
        InspectionEntityKind.STATION: snapshot.stations,
        InspectionEntityKind.TOWN: snapshot.towns,
        InspectionEntityKind.INDUSTRY: snapshot.industries,
    }
    return next((item for item in collections[entity_kind] if item.id == canonical_id), None)
