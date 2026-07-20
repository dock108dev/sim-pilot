from __future__ import annotations

import pytest
from pydantic import ValidationError

from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisSubjectType, AnalysisType
from sim_pilot.analysis.entity_inspection import (
    EntityInspectionError,
    InspectionEntityKind,
    InspectionEvidenceKind,
    InspectionResultStatus,
    evaluate_unsupported_inspection,
    resolve_inspection_action,
)
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.domain.world import Coordinates, Industry, Station, Town, Vehicle
from sim_pilot.openttd.gamescript.messages import CommandRequestPayload
from tests.analysis.helpers import snapshot

ANALYSIS_ID = f"analysis:{'a' * 20}"


def _vehicle(identifier: str, name: str = "Train 14") -> Vehicle:
    return Vehicle(
        id=identifier,
        type="rail",
        name=name,
        age_days=100,
        profit_this_year=-50,
        profit_last_year=-100,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )


def _record(*, second_vehicle: bool = False) -> AnalysisSessionRecord:
    vehicles = (_vehicle("vehicle-1"),)
    if second_vehicle:
        vehicles += (_vehicle("vehicle-2", "Train 15"),)
    world = snapshot(vehicles=vehicles)
    response = AnalysisService(default_analyzer_registry()).analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            question="Which vehicle lost money?",
        ),
        world,
    )
    response = response.model_copy(
        update={
            "snapshot_metadata": response.snapshot_metadata.model_copy(
                update={"bridge_company_context": 0}
            )
        }
    )
    return AnalysisSessionRecord(
        analysis_id=ANALYSIS_ID,
        response=response,
        snapshot=world,
    )


def test_named_entity_action_is_typed_and_deterministic() -> None:
    record = _record()
    finding_id = record.response.findings[0].finding_id

    first = resolve_inspection_action(record, finding_id)
    duplicate = resolve_inspection_action(record, finding_id)

    assert first == duplicate
    assert first.entity_kind is InspectionEntityKind.VEHICLE
    assert first.canonical_id == "vehicle-1"
    assert first.target_label == "Train 14"
    assert first.snapshot_identity.world_id == "world-1"


@pytest.mark.parametrize(
    ("subject", "kind", "entity", "collection"),
    (
        (
            AnalysisSubjectType.STATION,
            InspectionEntityKind.STATION,
            Station(
                id="station-1",
                name="Central",
                owner_id="company-1",
                coordinates=Coordinates(x=1, y=2),
            ),
            "stations",
        ),
        (
            AnalysisSubjectType.TOWN,
            InspectionEntityKind.TOWN,
            Town(
                id="town-1",
                name="Buntborough",
                population=500,
                coordinates=Coordinates(x=2, y=3),
            ),
            "towns",
        ),
        (
            AnalysisSubjectType.INDUSTRY,
            InspectionEntityKind.INDUSTRY,
            Industry(
                id="industry-1",
                type="coal_mine",
                name="Buntborough Mine",
                coordinates=Coordinates(x=3, y=4),
            ),
            "industries",
        ),
    ),
)
def test_supported_named_entity_kinds_resolve(
    subject: AnalysisSubjectType,
    kind: InspectionEntityKind,
    entity: Station | Town | Industry,
    collection: str,
) -> None:
    record = _record()
    finding = record.response.findings[0]
    evidence = finding.evidence[0].model_copy(
        update={"entity_type": subject, "entity_id": entity.id}
    )
    response = record.response.model_copy(
        update={
            "findings": (finding.model_copy(update={"evidence": (evidence,)}),),
            "presentation": None,
        }
    )
    world = record.snapshot.model_copy(update={"vehicles": (), collection: (entity,)})

    action = resolve_inspection_action(
        record.model_copy(update={"response": response, "snapshot": world}),
        finding.finding_id,
    )

    assert action.entity_kind is kind
    assert action.canonical_id == entity.id
    assert action.target_label == entity.name


def test_inspection_returns_honest_unsupported_result_without_execution() -> None:
    record = _record()
    action = resolve_inspection_action(record, record.response.findings[0].finding_id)

    result = evaluate_unsupported_inspection(
        action,
        record.snapshot,
        bridge_company_context=0,
        supported_actions=("set_company_name",),
    )

    assert result.status is InspectionResultStatus.UNSUPPORTED
    assert result.executed is False
    assert result.economic_mutation is False
    capability = next(
        item
        for item in result.verification_evidence
        if item.kind is InspectionEvidenceKind.CAPABILITY_NEGOTIATION
    )
    assert capability.passed is False
    assert "set_company_name" in capability.detail


def test_duplicate_explicit_delivery_is_idempotent_and_never_executes() -> None:
    record = _record()
    action = resolve_inspection_action(record, record.response.findings[0].finding_id)

    first = evaluate_unsupported_inspection(
        action,
        record.snapshot,
        bridge_company_context=0,
        supported_actions=("set_company_name",),
    )
    duplicate = evaluate_unsupported_inspection(
        action,
        record.snapshot,
        bridge_company_context=0,
        supported_actions=("set_company_name",),
    )

    assert duplicate == first
    assert duplicate.action.action_id == action.action_id
    assert duplicate.executed is False


def test_inspection_rejects_missing_and_ambiguous_references() -> None:
    record = _record(second_vehicle=True)
    finding = record.response.findings[0]
    second_evidence = finding.evidence[0].model_copy(update={"entity_id": "vehicle-2"})
    ambiguous_finding = finding.model_copy(
        update={"evidence": (*finding.evidence, second_evidence)}
    )
    ambiguous_response = record.response.model_copy(
        update={"findings": (ambiguous_finding,), "presentation": None}
    )
    ambiguous = record.model_copy(update={"response": ambiguous_response})

    with pytest.raises(EntityInspectionError, match="more than one") as error:
        resolve_inspection_action(ambiguous, finding.finding_id)
    assert error.value.code == "ambiguous_entity"

    missing = record.model_copy(
        update={"snapshot": record.snapshot.model_copy(update={"vehicles": ()})}
    )
    with pytest.raises(EntityInspectionError, match="absent") as error:
        resolve_inspection_action(missing, finding.finding_id)
    assert error.value.code == "missing_entity"


def test_inspection_rejects_wrong_world_restart_and_stale_entity() -> None:
    record = _record()
    action = resolve_inspection_action(record, record.response.findings[0].finding_id)
    wrong_world = record.snapshot.model_copy(
        update={
            "metadata": record.snapshot.metadata.model_copy(
                update={"world_id": "world-after-restart"}
            )
        }
    )
    with pytest.raises(EntityInspectionError, match="different OpenTTD world") as error:
        evaluate_unsupported_inspection(
            action,
            wrong_world,
            bridge_company_context=0,
            supported_actions=("set_company_name",),
        )
    assert error.value.code == "wrong_world"

    stale = record.snapshot.model_copy(update={"vehicles": ()})
    with pytest.raises(EntityInspectionError, match="absent") as error:
        evaluate_unsupported_inspection(
            action,
            stale,
            bridge_company_context=0,
            supported_actions=("set_company_name",),
        )
    assert error.value.code == "stale_reference"


@pytest.mark.parametrize(
    "change",
    (
        {"save_generation": 3},
        {"capability_fingerprint": "changed"},
        {"observer_company_id": "company-2"},
    ),
)
def test_inspection_rejects_stale_identity(change: dict[str, object]) -> None:
    record = _record()
    action = resolve_inspection_action(record, record.response.findings[0].finding_id)
    current = record.snapshot.model_copy(
        update={"metadata": record.snapshot.metadata.model_copy(update=change)}
    )

    with pytest.raises(EntityInspectionError, match="no longer matches") as error:
        evaluate_unsupported_inspection(
            action,
            current,
            bridge_company_context=0,
            supported_actions=("set_company_name",),
        )
    assert error.value.code == "stale_reference"


def test_protocol_does_not_accept_an_unproven_inspection_command() -> None:
    with pytest.raises(ValidationError):
        CommandRequestPayload.model_validate(
            {
                "action": "focus_named_entity",
                "command_id": "inspect-1",
                "parameters": {"name": "unchanged"},
                "action_fingerprint": "a" * 64,
                "expected_capability_fingerprint": "b" * 64,
                "expected_company_id": 0,
                "prior_snapshot_id": "snapshot-1",
                "request_timestamp": "2026-07-20T00:00:00Z",
            },
            strict=True,
        )
