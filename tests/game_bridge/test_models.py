import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sim_pilot.game_bridge.models import (
    BridgeEnvelope,
    CapabilityManifestPayload,
    CoverageStatus,
    FieldCoverage,
    Identity,
    IdentityStatus,
    MessageType,
    ObservationSurface,
    ObservedEntity,
    parse_envelope,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "game_bridge" / "v2"


@pytest.mark.parametrize(
    "name,message_type",
    [
        ("client_hello.json", MessageType.CLIENT_HELLO),
        ("bridge_hello.json", MessageType.BRIDGE_HELLO),
        ("capability_manifest.json", MessageType.CAPABILITY_MANIFEST),
        ("full_snapshot_response.json", MessageType.FULL_SNAPSHOT_RESPONSE),
        ("set_route_request.json", MessageType.SET_ROUTE_REQUEST),
        ("set_route_response.json", MessageType.SET_ROUTE_RESPONSE),
        ("protocol_error.json", MessageType.PROTOCOL_ERROR),
    ],
)
def test_cross_language_golden_fixtures_are_strict_and_canonical(
    name: str, message_type: MessageType
) -> None:
    raw = (FIXTURES / name).read_bytes().strip()
    parsed = parse_envelope(raw)

    assert parsed.message_type is message_type
    assert json.loads(parsed.to_json()) == json.loads(raw)


def test_unknown_missing_wrong_type_and_unknown_message_fail_closed() -> None:
    raw = json.loads((FIXTURES / "bridge_hello.json").read_text())
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate({**raw, "unknown": True}, strict=True)
    missing = {key: value for key, value in raw.items() if key != "game_id"}
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(missing, strict=True)
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate({**raw, "bridge_sequence": "1"}, strict=True)
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate({**raw, "message_type": "future"}, strict=True)


def test_payload_type_and_required_correlation_fail_closed() -> None:
    raw = json.loads((FIXTURES / "bridge_hello.json").read_text())
    raw["payload"] = {"healthy": True, "detail": None}
    with pytest.raises(ValidationError, match="BridgeHelloPayload"):
        parse_envelope(json.dumps(raw).encode())
    raw = json.loads((FIXTURES / "bridge_hello.json").read_text())
    raw["correlation_id"] = None
    with pytest.raises(ValidationError, match="correlation"):
        parse_envelope(json.dumps(raw).encode())


def test_identity_and_coverage_semantics_are_explicit() -> None:
    with pytest.raises(ValidationError, match="requires value"):
        Identity(status=IdentityStatus.OBSERVED)
    with pytest.raises(ValidationError, match="cannot have value"):
        Identity(status=IdentityStatus.UNAVAILABLE, value="invented")
    with pytest.raises(ValidationError, match="sorted"):
        FieldCoverage(
            surface="trains",
            status=CoverageStatus.OBSERVED_PARTIAL,
            fields=("speed", "name"),
        )
    with pytest.raises(ValidationError, match="cannot contain"):
        ObservationSurface(
            coverage=FieldCoverage(surface="trains", status=CoverageStatus.UNSUPPORTED),
            entities=(ObservedEntity(entity_type="train", entity_id="1", values={}),),
        )


def test_action_catalog_is_exact_and_surfaces_are_deterministic() -> None:
    with pytest.raises(ValidationError, match="only gameplay action"):
        CapabilityManifestPayload(observation_surfaces=("game_state",), gameplay_actions=("pause",))
    with pytest.raises(ValidationError, match="sorted"):
        CapabilityManifestPayload(observation_surfaces=("trains", "game_state"))


def test_oversized_and_malformed_json_fail_before_publication() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_envelope(b"{}" * 10, maximum_bytes=10)
    with pytest.raises(ValidationError):
        parse_envelope(b"not-json")
