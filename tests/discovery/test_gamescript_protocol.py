import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from discovery.openttd_gamescript import (
    BridgeCapabilities,
    BridgeEnvelope,
    DuplicateTracker,
    MessageType,
)

FIXTURES = Path(__file__).parents[2] / "discovery" / "openttd_gamescript" / "fixtures"


def envelope(**updates: object) -> BridgeEnvelope:
    values: dict[str, object] = {
        "sequence": 1,
        "message_id": "instance:1",
        "script_instance_id": "instance",
        "message_type": MessageType.HELLO,
        "game_date": 712223,
        "payload": {},
    }
    values.update(updates)
    return BridgeEnvelope.model_validate(values, strict=True)


def test_envelope_round_trip_and_unknown_field_rejection() -> None:
    value = envelope()
    assert BridgeEnvelope.from_json(value.to_json()) == value
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate({**value.model_dump(), "unknown": True}, strict=True)


def test_command_response_requires_correlation_and_size_is_bounded() -> None:
    with pytest.raises(ValidationError, match="correlation"):
        envelope(message_type=MessageType.COMMAND_COMPLETED)
    with pytest.raises(ValueError, match="exceeds"):
        envelope(payload={"value": "x" * 2000}).to_json()


def test_malformed_json_version_and_duplicate_detection() -> None:
    with pytest.raises(ValidationError):
        BridgeEnvelope.from_json("not-json")
    with pytest.raises(ValidationError):
        BridgeEnvelope.from_json(
            envelope().to_json().replace('"protocol_version":1', '"protocol_version":2')
        )
    tracker = DuplicateTracker(capacity=2)
    assert tracker.accept("one") is True
    assert tracker.accept("one") is False
    assert tracker.accept("two") is True
    assert tracker.accept("three") is True
    assert tracker.accept("one") is True


def test_capabilities_are_strict_and_round_trip() -> None:
    capabilities = BridgeCapabilities(
        read_resources=("companies", "towns"),
        write_actions=("set_company_name",),
        company_contexts=("existing_company",),
        cost_estimation=True,
        command_deduplication=True,
    )
    assert BridgeCapabilities.model_validate_json(capabilities.model_dump_json()) == capabilities
    with pytest.raises(ValidationError):
        BridgeCapabilities.model_validate({"protocol_version": 1, "invented": True})


def test_fixture_loads_as_typed_gamescript_message() -> None:
    raw = (FIXTURES / "hello.json").read_text()
    message = BridgeEnvelope.from_json(raw)
    assert message.message_type is MessageType.HELLO
    assert message.payload["api_version"] == "15"


def test_unsupported_message_type_is_rejected() -> None:
    raw = json.loads(envelope().to_json())
    raw["message_type"] = "future_message"
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(raw)


@pytest.mark.parametrize("sequence", [0, -1])
def test_sequence_must_be_positive(sequence: int) -> None:
    with pytest.raises(ValidationError):
        envelope(sequence=sequence)


def test_production_bridge_does_not_import_discovery_support() -> None:
    production = Path(__file__).parents[2] / "src" / "sim_pilot"
    bridge_files = tuple((production / "openttd" / "gamescript").glob("*.py"))

    assert bridge_files
    for path in bridge_files:
        assert "discovery" not in path.read_text(encoding="utf-8")
