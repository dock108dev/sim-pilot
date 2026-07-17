"""Strict versioned messages for the OpenTTD GameScript bridge protocol v1."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

BRIDGE_PROTOCOL_VERSION = 1
GAMESCRIPT_TO_ADMIN_MAX_BYTES = 1450
ADMIN_TO_GAMESCRIPT_MAX_BYTES = 8999
SIM_PILOT_ADAPTER_VERSION = "openttd-gamescript-v1"


class BridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MessageType(StrEnum):
    HELLO = "hello"
    CAPABILITIES = "capabilities"
    HEARTBEAT = "heartbeat"
    STATE_SNAPSHOT = "state_snapshot"
    COMMAND_REQUEST = "command_request"
    COMMAND_ACCEPTED = "command_accepted"
    COMMAND_REJECTED = "command_rejected"
    COMMAND_COMPLETED = "command_completed"
    COMMAND_FAILED = "command_failed"
    RESYNC_REQUEST = "resync_request"
    RESYNC_RESPONSE = "resync_response"
    SAVE = "save"
    LOAD = "load"
    ERROR = "error"


class ErrorCode(StrEnum):
    UNSUPPORTED_COMMAND = "unsupported_command"
    INVALID_COMPANY = "invalid_company"
    INVALID_PARAMETERS = "invalid_parameters"
    GAME_RULE_REJECTION = "game_rule_rejection"
    STALE_REQUEST = "stale_request"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    INTERNAL_SCRIPT_FAILURE = "internal_script_failure"
    WRITES_DISABLED = "writes_disabled"


class HelloPayload(BridgeModel):
    component: Literal["sim_pilot_bridge"] = "sim_pilot_bridge"
    openttd_version: Literal["15.3"] = "15.3"
    gamescript_api_version: Literal["15"] = "15"
    script_version: Literal[1] = 1
    adapter_version: Literal["openttd-gamescript-v1"] = SIM_PILOT_ADAPTER_VERSION
    loaded: bool
    save_generation: int = Field(ge=0)
    start_generation: int = Field(ge=1)


class BridgeCapabilities(BridgeModel):
    capability_version: Literal[1] = 1
    readable_resources: tuple[str, ...]
    readable_entities: tuple[str, ...]
    event_types: tuple[str, ...] = ()
    supported_actions: tuple[str, ...]
    company_contexts: tuple[str, ...]
    cost_estimation: bool
    independent_verification: bool
    reconciliation: bool
    save_load: bool
    full_snapshots: bool
    state_deltas: Literal[False] = False
    maximum_outbound_bytes: Literal[1450] = 1450
    maximum_inbound_bytes: Literal[8999] = 8999
    write_opt_in_required: Literal[True] = True

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json(exclude_none=True).encode("utf-8")).hexdigest()


class HeartbeatPayload(BridgeModel):
    tick: int = Field(ge=0)
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=128)
    healthy: bool = True


class BridgeCompanySnapshot(BridgeModel):
    company_id: int = Field(ge=0, le=14)
    name: str = Field(min_length=1)
    cash: int
    loan: int = Field(ge=0)
    vehicle_count: int = Field(ge=0)
    station_count: int = Field(ge=0)


class BridgeSnapshot(BridgeModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    paused: bool
    map_width: int = Field(gt=0)
    map_height: int = Field(gt=0)
    town_count: int = Field(ge=0)
    industry_count: int = Field(ge=0)
    company: BridgeCompanySnapshot | None
    save_generation: int = Field(ge=0)


class SetCompanyNameParameters(BridgeModel):
    name: str = Field(min_length=1, max_length=128)


class CommandRequestPayload(BridgeModel):
    command_id: str = Field(min_length=1, max_length=128)
    action: Literal["set_company_name"] = "set_company_name"
    parameters: SetCompanyNameParameters
    action_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_company_id: int = Field(ge=0, le=14)
    prior_snapshot_id: str = Field(min_length=1, max_length=128)
    request_timestamp: str = Field(min_length=1)


class CommandAcceptedPayload(BridgeModel):
    command_id: str = Field(min_length=1, max_length=128)
    action_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CommandCompletedPayload(BridgeModel):
    command_id: str = Field(min_length=1, max_length=128)
    action_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["set_company_name"] = "set_company_name"
    before_name: str = Field(min_length=1)
    after_name: str = Field(min_length=1)
    state_changed: bool
    cost: int = Field(ge=0)
    duplicate: bool = False


class BridgeErrorPayload(BridgeModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    command_id: str | None = Field(default=None, min_length=1, max_length=128)
    action_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retryable: bool = False


class ResyncRequestPayload(BridgeModel):
    last_script_instance_id: str | None = Field(default=None, max_length=128)
    last_sequence: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=128)


class ResyncResponsePayload(BridgeModel):
    snapshot_follows: Literal[True] = True
    reason: str = Field(min_length=1, max_length=128)


class SaveLoadPayload(BridgeModel):
    save_generation: int = Field(ge=0)
    sequence: int = Field(ge=0)


BridgePayload = Annotated[
    HelloPayload
    | BridgeCapabilities
    | HeartbeatPayload
    | BridgeSnapshot
    | CommandRequestPayload
    | CommandAcceptedPayload
    | CommandCompletedPayload
    | BridgeErrorPayload
    | ResyncRequestPayload
    | ResyncResponsePayload
    | SaveLoadPayload,
    Field(union_mode="left_to_right"),
]


_PAYLOAD_TYPES: dict[MessageType, type[BridgeModel]] = {
    MessageType.HELLO: HelloPayload,
    MessageType.CAPABILITIES: BridgeCapabilities,
    MessageType.HEARTBEAT: HeartbeatPayload,
    MessageType.STATE_SNAPSHOT: BridgeSnapshot,
    MessageType.COMMAND_REQUEST: CommandRequestPayload,
    MessageType.COMMAND_ACCEPTED: CommandAcceptedPayload,
    MessageType.COMMAND_REJECTED: BridgeErrorPayload,
    MessageType.COMMAND_COMPLETED: CommandCompletedPayload,
    MessageType.COMMAND_FAILED: BridgeErrorPayload,
    MessageType.RESYNC_REQUEST: ResyncRequestPayload,
    MessageType.RESYNC_RESPONSE: ResyncResponsePayload,
    MessageType.SAVE: SaveLoadPayload,
    MessageType.LOAD: SaveLoadPayload,
    MessageType.ERROR: BridgeErrorPayload,
}


class BridgeMessage(BridgeModel):
    protocol_version: Literal[1] = BRIDGE_PROTOCOL_VERSION
    sequence: int = Field(ge=1)
    message_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    script_instance_id: str = Field(min_length=1, max_length=128)
    message_type: MessageType
    game_date: int = Field(ge=0)
    company_id: int | None = Field(default=None, ge=0, le=14)
    payload: BridgePayload

    @model_validator(mode="after")
    def validate_payload_and_correlation(self) -> Self:
        expected = _PAYLOAD_TYPES[self.message_type]
        if not isinstance(self.payload, expected):
            raise ValueError(f"{self.message_type.value} requires payload {expected.__name__}")
        if (
            self.message_type
            in {
                MessageType.COMMAND_ACCEPTED,
                MessageType.COMMAND_REJECTED,
                MessageType.COMMAND_COMPLETED,
                MessageType.COMMAND_FAILED,
                MessageType.RESYNC_RESPONSE,
            }
            and self.correlation_id is None
        ):
            raise ValueError(f"{self.message_type.value} requires correlation_id")
        return self

    def to_json(self, *, maximum_bytes: int) -> str:
        value = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(value.encode("utf-8")) > maximum_bytes:
            raise ValueError(f"bridge message exceeds {maximum_bytes} bytes")
        return value


_MESSAGE_ADAPTER = TypeAdapter(BridgeMessage)


def parse_bridge_message(
    value: str, *, maximum_bytes: int = GAMESCRIPT_TO_ADMIN_MAX_BYTES
) -> BridgeMessage:
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"bridge message exceeds {maximum_bytes} bytes")
    return _MESSAGE_ADAPTER.validate_json(value, strict=True)
