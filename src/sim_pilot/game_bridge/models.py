"""Strict read-only protocol-v3 contracts shared by game bridge adapters."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

PROTOCOL_VERSION = 3
DEFAULT_MAXIMUM_MESSAGE_BYTES = 1_048_576

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class BridgeModel(BaseModel):
    """Base contract: immutable, strict, and closed to unknown keys."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Platform(StrEnum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"


class Architecture(StrEnum):
    X86_64 = "x86_64"
    ARM64 = "arm64"


class IdentityStatus(StrEnum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


class Identity(BridgeModel):
    status: IdentityStatus
    value: str | None = Field(default=None, min_length=1, max_length=256)
    label: str | None = Field(default=None, min_length=1, max_length=256)
    detail: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status is IdentityStatus.OBSERVED and self.value is None:
            raise ValueError("observed identity requires value")
        if self.status is IdentityStatus.UNAVAILABLE and self.value is not None:
            raise ValueError("unavailable identity cannot have value")
        return self


class CoverageStatus(StrEnum):
    OBSERVED_COMPLETE = "observed_complete"
    OBSERVED_PARTIAL = "observed_partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class FieldCoverage(BridgeModel):
    surface: str = Field(min_length=1, max_length=128)
    status: CoverageStatus
    fields: tuple[str, ...] = ()
    detail: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if tuple(sorted(set(self.fields))) != self.fields:
            raise ValueError("coverage fields must be unique and sorted")
        return self


class ObservedEntity(BridgeModel):
    entity_type: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=256)
    values: dict[str, JsonValue]


class ObservationSurface(BridgeModel):
    coverage: FieldCoverage
    entities: tuple[ObservedEntity, ...] = ()

    @model_validator(mode="after")
    def validate_surface(self) -> Self:
        if (
            self.coverage.status
            in {
                CoverageStatus.UNSUPPORTED,
                CoverageStatus.UNAVAILABLE,
                CoverageStatus.FAILED,
            }
            and self.entities
        ):
            raise ValueError("unobserved surface cannot contain entities")
        keys = tuple((item.entity_type, item.entity_id) for item in self.entities)
        if tuple(sorted(set(keys))) != keys:
            raise ValueError("surface entities must have unique, deterministic ordering")
        return self


class GameSnapshot(BridgeModel):
    schema_version: Literal[1] = 1
    capture_timestamp: AwareDatetime
    capture_started_marker: str = Field(min_length=1, max_length=256)
    capture_completed_marker: str = Field(min_length=1, max_length=256)
    bridge_sequence: int = Field(ge=1)
    bridge_instance_id: str = Field(min_length=1, max_length=128)
    game_session_id: str = Field(min_length=1, max_length=128)
    game_id: str = Field(min_length=1, max_length=128)
    game_version: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=128)
    platform: Platform
    architecture: Architecture
    map_identity: Identity
    save_identity: Identity
    game_state: dict[str, JsonValue]
    surfaces: tuple[ObservationSurface, ...]
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_deterministic_surfaces(self) -> Self:
        names = tuple(item.coverage.surface for item in self.surfaces)
        if tuple(sorted(set(names))) != names:
            raise ValueError("snapshot surfaces must have unique, deterministic ordering")
        return self

    def to_canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class MessageType(StrEnum):
    CLIENT_HELLO = "client_hello"
    BRIDGE_HELLO = "bridge_hello"
    AUTHENTICATION_FAILURE = "authentication_failure"
    HEARTBEAT = "heartbeat"
    CAPABILITY_MANIFEST = "capability_manifest"
    FULL_SNAPSHOT_REQUEST = "full_snapshot_request"
    FULL_SNAPSHOT_RESPONSE = "full_snapshot_response"
    RESYNCHRONIZATION_REQUEST = "resynchronization_request"
    PROTOCOL_ERROR = "protocol_error"


class ClientHelloPayload(BridgeModel):
    authentication_token: str = Field(min_length=32, max_length=512, repr=False)
    client_instance_id: str = Field(min_length=1, max_length=128)
    requested_protocol_version: Literal[3] = 3
    expected_adapter_version: str = Field(min_length=1, max_length=128)
    expected_game_id: str = Field(min_length=1, max_length=128)
    expected_game_version: str = Field(min_length=1, max_length=128)


class BridgeHelloPayload(BridgeModel):
    authenticated: Literal[True] = True
    negotiated_protocol_version: Literal[3] = 3
    maximum_message_bytes: int = Field(ge=1024, le=16_777_216)
    heartbeat_interval_seconds: float = Field(gt=0, le=300)


class AuthenticationFailurePayload(BridgeModel):
    reason: Literal["authentication_failed"] = "authentication_failed"


class HeartbeatPayload(BridgeModel):
    healthy: bool
    detail: str | None = Field(default=None, min_length=1, max_length=512)


class CapabilityManifestPayload(BridgeModel):
    schema_version: Literal[1] = 1
    observation_surfaces: tuple[str, ...]
    gameplay_actions: tuple[()] = ()
    full_snapshots: Literal[True] = True
    delta_snapshots: Literal[False] = False
    resynchronization: Literal[True] = True

    @model_validator(mode="after")
    def enforce_capabilities_and_ordering(self) -> Self:
        if self.gameplay_actions:
            raise ValueError("the UI-observer bridge gameplay action catalog must be empty")
        if tuple(sorted(set(self.observation_surfaces))) != self.observation_surfaces:
            raise ValueError("observation surfaces must be unique and sorted")
        return self


class FullSnapshotRequestPayload(BridgeModel):
    expected_bridge_instance_id: str = Field(min_length=1, max_length=128)
    expected_game_session_id: str = Field(min_length=1, max_length=128)


class FullSnapshotResponsePayload(BridgeModel):
    snapshot: GameSnapshot


class ResynchronizationRequestPayload(BridgeModel):
    last_bridge_instance_id: str | None = Field(default=None, min_length=1, max_length=128)
    last_game_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    last_bridge_sequence: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=128)


class ProtocolErrorCode(StrEnum):
    MALFORMED_ENVELOPE = "malformed_envelope"
    UNKNOWN_MESSAGE_TYPE = "unknown_message_type"
    MESSAGE_TOO_LARGE = "message_too_large"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    ADAPTER_MISMATCH = "adapter_mismatch"
    GAME_MISMATCH = "game_mismatch"
    DUPLICATE_MESSAGE = "duplicate_message"
    SEQUENCE_ERROR = "sequence_error"
    STALE_IDENTITY = "stale_identity"
    SNAPSHOT_FAILED = "snapshot_failed"
    INTERNAL_ERROR = "internal_error"


class ProtocolErrorPayload(BridgeModel):
    code: ProtocolErrorCode
    message: str = Field(min_length=1, max_length=1024)
    retryable: bool = False


BridgePayload = Annotated[
    ClientHelloPayload
    | BridgeHelloPayload
    | AuthenticationFailurePayload
    | HeartbeatPayload
    | CapabilityManifestPayload
    | FullSnapshotRequestPayload
    | FullSnapshotResponsePayload
    | ResynchronizationRequestPayload
    | ProtocolErrorPayload,
    Field(union_mode="left_to_right"),
]

_PAYLOAD_TYPES: dict[MessageType, type[BridgeModel]] = {
    MessageType.CLIENT_HELLO: ClientHelloPayload,
    MessageType.BRIDGE_HELLO: BridgeHelloPayload,
    MessageType.AUTHENTICATION_FAILURE: AuthenticationFailurePayload,
    MessageType.HEARTBEAT: HeartbeatPayload,
    MessageType.CAPABILITY_MANIFEST: CapabilityManifestPayload,
    MessageType.FULL_SNAPSHOT_REQUEST: FullSnapshotRequestPayload,
    MessageType.FULL_SNAPSHOT_RESPONSE: FullSnapshotResponsePayload,
    MessageType.RESYNCHRONIZATION_REQUEST: ResynchronizationRequestPayload,
    MessageType.PROTOCOL_ERROR: ProtocolErrorPayload,
}


class BridgeEnvelope(BridgeModel):
    protocol_version: Literal[3] = 3
    adapter_version: str = Field(min_length=1, max_length=128)
    game_id: str = Field(min_length=1, max_length=128)
    game_version: str = Field(min_length=1, max_length=128)
    platform: Platform
    architecture: Architecture
    bridge_instance_id: str = Field(min_length=1, max_length=128)
    game_session_id: str = Field(min_length=1, max_length=128)
    map_identity: Identity
    save_identity: Identity
    message_id: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    bridge_sequence: int = Field(ge=1)
    message_type: MessageType
    timestamp: AwareDatetime
    payload: BridgePayload

    @model_validator(mode="after")
    def validate_payload_and_correlation(self) -> Self:
        expected = _PAYLOAD_TYPES[self.message_type]
        if not isinstance(self.payload, expected):
            raise ValueError(f"{self.message_type.value} requires {expected.__name__}")
        if (
            self.message_type
            in {
                MessageType.BRIDGE_HELLO,
                MessageType.AUTHENTICATION_FAILURE,
                MessageType.FULL_SNAPSHOT_RESPONSE,
            }
            and self.correlation_id is None
        ):
            raise ValueError(f"{self.message_type.value} requires correlation_id")
        return self

    def to_json(self, *, maximum_bytes: int = DEFAULT_MAXIMUM_MESSAGE_BYTES) -> bytes:
        value = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(value) > maximum_bytes:
            raise ValueError(f"bridge message exceeds {maximum_bytes} bytes")
        return value


_ENVELOPE_ADAPTER = TypeAdapter(BridgeEnvelope)


def parse_envelope(
    value: bytes, *, maximum_bytes: int = DEFAULT_MAXIMUM_MESSAGE_BYTES
) -> BridgeEnvelope:
    if len(value) > maximum_bytes:
        raise ValueError(f"bridge message exceeds {maximum_bytes} bytes")
    return _ENVELOPE_ADAPTER.validate_json(value, strict=True)
