"""Strict versioned messages for the OpenTTD GameScript bridge protocol v1."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

BRIDGE_PROTOCOL_VERSION = 2
GAMESCRIPT_TO_ADMIN_MAX_BYTES = 1450
ADMIN_TO_GAMESCRIPT_MAX_BYTES = 8999
SIM_PILOT_ADAPTER_VERSION = "openttd-gamescript-v2"


class BridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MessageType(StrEnum):
    HELLO = "hello"
    CAPABILITIES = "capabilities"
    HEARTBEAT = "heartbeat"
    STATE_SNAPSHOT = "state_snapshot"
    WORLD_MANIFEST = "world_manifest"
    WORLD_COLLECTION_PAGE = "world_collection_page"
    WORLD_SNAPSHOT_COMPLETE = "world_snapshot_complete"
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
    script_version: Literal[1, 2] = 2
    adapter_version: Literal["openttd-gamescript-v1", "openttd-gamescript-v2"] = (
        SIM_PILOT_ADAPTER_VERSION
    )
    loaded: bool
    save_generation: int = Field(ge=0)
    start_generation: int = Field(ge=1)


class BridgeCapabilities(BridgeModel):
    capability_version: Literal[1, 2] = 1
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
    world_snapshots: bool = False
    world_collections: tuple[str, ...] = ()

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


class WorldCollection(StrEnum):
    COMPANIES = "companies"
    TOWNS = "towns"
    INDUSTRIES = "industries"
    STATIONS = "stations"
    VEHICLES = "vehicles"
    ORDERS = "orders"
    CARGOS = "cargos"


class BridgeCompanyEntity(BridgeModel):
    entity_type: Literal["company"] = "company"
    id: int = Field(ge=0, le=14)
    name: str = Field(min_length=1)
    cash: int
    loan: int = Field(ge=0)
    company_value: int | None = None
    income: int | None = None
    expenses: int | None = None
    performance: int | None = Field(default=None, ge=0)
    headquarters_tile: int | None = Field(default=None, ge=0)
    station_count: int = Field(default=0, ge=0)


class BridgeTownEntity(BridgeModel):
    entity_type: Literal["town"] = "town"
    id: int = Field(ge=0)
    name: str = Field(min_length=1)
    population: int = Field(ge=0)
    tile: int = Field(ge=0)
    growth_rate: int | None = Field(default=None, ge=0)
    rating: int | None = Field(default=None, ge=-1000, le=1000)


class BridgeIndustryEntity(BridgeModel):
    entity_type: Literal["industry"] = "industry"
    id: int = Field(ge=0)
    industry_type: int = Field(ge=0)
    name: str = Field(min_length=1)
    tile: int = Field(ge=0)
    nearby_station_count: int = Field(ge=0)
    accepted_cargo_ids: tuple[int, ...] = ()
    produced_cargo_ids: tuple[int, ...] = ()


class BridgeStationEntity(BridgeModel):
    entity_type: Literal["station"] = "station"
    id: int = Field(ge=0)
    name: str = Field(min_length=1)
    owner: int = Field(ge=0, le=14)
    tile: int = Field(ge=0)
    facilities: tuple[str, ...] = ()


class BridgeVehicleEntity(BridgeModel):
    entity_type: Literal["vehicle"] = "vehicle"
    id: int = Field(ge=0)
    owner: int = Field(ge=0, le=14)
    vehicle_type: int = Field(ge=0)
    engine_type: int = Field(ge=0)
    name: str = Field(min_length=1)
    age_days: int = Field(ge=0)
    profit_this_year: int
    profit_last_year: int
    state: int = Field(ge=0)
    tile: int | None = Field(default=None, ge=0)
    in_depot: bool
    current_order_index: int | None = Field(default=None, ge=0)


class BridgeOrderEntity(BridgeModel):
    entity_type: Literal["order"] = "order"
    vehicle_id: int = Field(ge=0)
    index: int = Field(ge=0)
    kind: str = Field(min_length=1)
    destination_tile: int | None = Field(default=None, ge=0)
    destination_station_id: int | None = Field(default=None, ge=0)
    flags: int | None = Field(default=None, ge=0)


class BridgeCargoEntity(BridgeModel):
    entity_type: Literal["cargo"] = "cargo"
    id: int = Field(ge=0)
    name: str = Field(min_length=1)
    scope: Literal["world", "town", "industry", "station"] = "world"
    scope_entity_id: int | None = Field(default=None, ge=0)
    waiting: int | None = Field(default=None, ge=0)
    produced: int | None = Field(default=None, ge=0)
    accepted: bool | None = None
    transported: int | None = Field(default=None, ge=0)
    transported_percent: int | None = Field(default=None, ge=0, le=100)


BridgeWorldEntity = Annotated[
    BridgeCompanyEntity
    | BridgeTownEntity
    | BridgeIndustryEntity
    | BridgeStationEntity
    | BridgeVehicleEntity
    | BridgeOrderEntity
    | BridgeCargoEntity,
    Field(discriminator="entity_type"),
]


class WorldManifestPayload(BridgeModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    capture_started_game_date: int = Field(ge=0)
    collection_counts: dict[str, int]


class WorldCollectionPagePayload(BridgeModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    collection: WorldCollection
    page_index: int = Field(ge=0)
    page_count: int = Field(ge=0)
    items: tuple[BridgeWorldEntity, ...]

    @model_validator(mode="after")
    def validate_collection_items(self) -> Self:
        expected: dict[WorldCollection, type[BridgeModel]] = {
            WorldCollection.COMPANIES: BridgeCompanyEntity,
            WorldCollection.TOWNS: BridgeTownEntity,
            WorldCollection.INDUSTRIES: BridgeIndustryEntity,
            WorldCollection.STATIONS: BridgeStationEntity,
            WorldCollection.VEHICLES: BridgeVehicleEntity,
            WorldCollection.ORDERS: BridgeOrderEntity,
            WorldCollection.CARGOS: BridgeCargoEntity,
        }
        if any(not isinstance(item, expected[self.collection]) for item in self.items):
            raise ValueError(f"{self.collection.value} page contains the wrong entity type")
        return self


class WorldSnapshotCompletePayload(BridgeModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    capture_completed_game_date: int = Field(ge=0)
    total_items: int = Field(ge=0)


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
    | WorldManifestPayload
    | WorldCollectionPagePayload
    | WorldSnapshotCompletePayload
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
    MessageType.WORLD_MANIFEST: WorldManifestPayload,
    MessageType.WORLD_COLLECTION_PAGE: WorldCollectionPagePayload,
    MessageType.WORLD_SNAPSHOT_COMPLETE: WorldSnapshotCompletePayload,
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
    protocol_version: Literal[1, 2] = BRIDGE_PROTOCOL_VERSION
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
