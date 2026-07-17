import json

import pytest
from pydantic import ValidationError

from sim_pilot.openttd.gamescript.messages import (
    BridgeErrorPayload,
    BridgeMessage,
    ErrorCode,
    HelloPayload,
    MessageType,
    parse_bridge_message,
)
from tests.openttd.gamescript.helpers import capabilities, message, snapshot


def test_every_production_inbound_payload_round_trips_deterministically() -> None:
    values = (
        message(
            1,
            MessageType.HELLO,
            HelloPayload(loaded=False, save_generation=0, start_generation=1),
        ),
        message(2, MessageType.CAPABILITIES, capabilities()),
        message(3, MessageType.STATE_SNAPSHOT, snapshot()),
        message(
            4,
            MessageType.ERROR,
            BridgeErrorPayload(code=ErrorCode.INTERNAL_SCRIPT_FAILURE, message="failed"),
        ),
    )
    for raw in values:
        parsed = parse_bridge_message(raw)
        assert parsed.to_json(maximum_bytes=1450) == raw


def test_unknown_fields_types_versions_and_payload_mismatch_fail_closed() -> None:
    raw = json.loads(
        message(
            1,
            MessageType.HELLO,
            HelloPayload(loaded=False, save_generation=0, start_generation=1),
        )
    )
    for key, value in (
        ("unknown", True),
        ("protocol_version", 2),
        ("message_type", "state_delta"),
    ):
        invalid = {**raw, key: value}
        with pytest.raises(ValidationError):
            BridgeMessage.model_validate(invalid, strict=True)
    raw["message_type"] = MessageType.HEARTBEAT
    with pytest.raises(ValidationError, match="HeartbeatPayload"):
        BridgeMessage.model_validate(raw, strict=True)


def test_payload_size_malformed_json_and_correlation_are_validated() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_bridge_message("{}" * 1000, maximum_bytes=10)
    with pytest.raises(ValidationError):
        parse_bridge_message("not-json")
    with pytest.raises(ValidationError, match="correlation"):
        BridgeMessage.model_validate(
            {
                "sequence": 1,
                "message_id": "m",
                "script_instance_id": "s",
                "message_type": MessageType.COMMAND_REJECTED,
                "game_date": 1,
                "payload": BridgeErrorPayload(
                    code=ErrorCode.UNSUPPORTED_COMMAND, message="unsupported"
                ),
            },
            strict=True,
        )


def test_capability_fingerprint_is_stable() -> None:
    assert capabilities().fingerprint == (
        "a4868cb5227ad0e126764cb2312b52573218087ab6f5d145a7c8a60877db55ca"
    )
