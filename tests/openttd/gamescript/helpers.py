from __future__ import annotations

import hashlib
import json
from collections import deque

from sim_pilot.openttd.gamescript.messages import (
    BridgeCapabilities,
    BridgeCargoEntity,
    BridgeCompanyEntity,
    BridgeCompanySnapshot,
    BridgeIndustryEntity,
    BridgeMessage,
    BridgeOrderEntity,
    BridgeSnapshot,
    BridgeStationEntity,
    BridgeTownEntity,
    BridgeVehicleEntity,
    BridgeWorldEntity,
    CommandAcceptedPayload,
    CommandCompletedPayload,
    HelloPayload,
    MessageType,
    ResyncResponsePayload,
    WorldCollection,
    WorldCollectionPagePayload,
    WorldManifestPayload,
    WorldSnapshotCompletePayload,
)
from sim_pilot.openttd.models import OpenTTDConnectionMetadata


def capabilities(*, world: bool = False) -> BridgeCapabilities:
    return BridgeCapabilities(
        capability_version=2 if world else 1,
        readable_resources=(
            "paused",
            "map_width",
            "map_height",
            "town_count",
            "industry_count",
            "company_name",
            "company_cash",
            "company_loan",
            "vehicle_count",
            "station_count",
        ),
        readable_entities=("company", "town_summary", "industry_summary"),
        supported_actions=("set_company_name",),
        company_contexts=("existing_company",),
        cost_estimation=True,
        independent_verification=True,
        reconciliation=True,
        save_load=True,
        full_snapshots=True,
        world_snapshots=world,
        world_collections=tuple(item.value for item in WorldCollection) if world else (),
    )


def snapshot(
    name: str = "Fixture Transport", snapshot_id: str = "bridge:snapshot:4"
) -> BridgeSnapshot:
    return BridgeSnapshot(
        snapshot_id=snapshot_id,
        paused=False,
        map_width=256,
        map_height=256,
        town_count=12,
        industry_count=8,
        company=BridgeCompanySnapshot(
            company_id=0,
            name=name,
            cash=425000,
            loan=50000,
            vehicle_count=19,
            station_count=16,
        ),
        save_generation=2,
    )


def message(
    sequence: int,
    message_type: MessageType,
    payload: object,
    *,
    correlation_id: str | None = None,
    instance_id: str = "bridge-instance",
) -> str:
    return BridgeMessage.model_validate(
        {
            "sequence": sequence,
            "message_id": f"{instance_id}:{sequence}",
            "correlation_id": correlation_id,
            "script_instance_id": instance_id,
            "message_type": message_type,
            "game_date": 712223,
            "company_id": 0,
            "payload": payload,
        },
        strict=True,
    ).to_json(maximum_bytes=1450)


def sync_messages(
    start: int = 1,
    *,
    name: str = "Fixture Transport",
    instance_id: str = "bridge-instance",
) -> list[str]:
    return [
        message(
            start,
            MessageType.HELLO,
            HelloPayload(loaded=True, save_generation=2, start_generation=3),
            instance_id=instance_id,
        ),
        message(
            start + 1,
            MessageType.CAPABILITIES,
            capabilities(),
            instance_id=instance_id,
        ),
        message(
            start + 2,
            MessageType.RESYNC_RESPONSE,
            ResyncResponsePayload(reason="test"),
            correlation_id="CORRELATION",
            instance_id=instance_id,
        ),
        message(
            start + 3,
            MessageType.STATE_SNAPSHOT,
            snapshot(name, f"bridge:snapshot:{start + 3}"),
            instance_id=instance_id,
        ),
    ]


def world_sync_messages() -> list[str]:
    values: dict[WorldCollection, BridgeWorldEntity] = {
        WorldCollection.COMPANIES: BridgeCompanyEntity(
            id=0, name="Fixture Transport", cash=425000, loan=50000, station_count=1
        ),
        WorldCollection.TOWNS: BridgeTownEntity(
            id=1, name="Town", population=100, tile=257, growth_rate=10, rating=500
        ),
        WorldCollection.INDUSTRIES: BridgeIndustryEntity(
            id=2, industry_type=3, name="Mine", tile=514, nearby_station_count=1
        ),
        WorldCollection.STATIONS: BridgeStationEntity(
            id=4, name="Town Station", owner=0, tile=258, facilities=("rail",)
        ),
        WorldCollection.VEHICLES: BridgeVehicleEntity(
            id=5,
            owner=0,
            vehicle_type=0,
            engine_type=1,
            name="Train 1",
            age_days=20,
            profit_this_year=100,
            profit_last_year=90,
            state=0,
            tile=259,
            in_depot=False,
            current_order_index=0,
        ),
        WorldCollection.ORDERS: BridgeOrderEntity(
            vehicle_id=5,
            index=0,
            kind="station",
            destination_tile=258,
            destination_station_id=4,
            flags=0,
        ),
        WorldCollection.CARGOS: BridgeCargoEntity(id=0, name="Passengers"),
    }
    counts = {collection.value: 1 for collection in WorldCollection}
    result = sync_messages()
    result[1] = message(2, MessageType.CAPABILITIES, capabilities(world=True))
    result.append(
        message(
            5,
            MessageType.WORLD_MANIFEST,
            WorldManifestPayload(
                snapshot_id="world-1",
                capture_started_game_date=712223,
                collection_counts=counts,
            ),
        )
    )
    sequence = 6
    for collection in WorldCollection:
        result.append(
            message(
                sequence,
                MessageType.WORLD_COLLECTION_PAGE,
                WorldCollectionPagePayload(
                    snapshot_id="world-1",
                    collection=collection,
                    page_index=0,
                    page_count=1,
                    items=(values[collection],),
                ),
            )
        )
        sequence += 1
    result.append(
        message(
            sequence,
            MessageType.WORLD_SNAPSHOT_COMPLETE,
            WorldSnapshotCompletePayload(
                snapshot_id="world-1",
                capture_completed_game_date=712224,
                total_items=len(WorldCollection),
            ),
        )
    )
    return result


class FakeBridgeTransport:
    def __init__(self, messages: list[str]) -> None:
        self.messages = deque(messages)
        self.sent: list[str] = []
        self.connected = False
        self.closed = False
        self.subscriptions = 0
        self._metadata = OpenTTDConnectionMetadata(
            protocol_version=3,
            openttd_version="15.3",
            server_name="Fixture Server",
            dedicated=True,
        )

    @property
    def metadata(self) -> OpenTTDConnectionMetadata:
        return self._metadata

    async def connect(self) -> None:
        self.connected = True

    async def subscribe_gamescript(self) -> None:
        self.subscriptions += 1

    async def send_gamescript(self, value: str) -> None:
        self.sent.append(value)
        request = json.loads(value)
        if request["message_type"] == "resync_request":
            correlation = request["message_id"]
            for index, raw in enumerate(self.messages):
                parsed = json.loads(raw)
                if (
                    parsed["message_type"] == "resync_response"
                    and parsed["correlation_id"] == "CORRELATION"
                ):
                    parsed["correlation_id"] = correlation
                    self.messages[index] = json.dumps(parsed, sort_keys=True, separators=(",", ":"))

    async def receive_gamescript(self, timeout: float | None = None) -> str:
        del timeout
        return self.messages.popleft()

    async def reconnect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True
        self.connected = False


def command_fingerprint(name: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": "set_company_name",
                "company_id": 0,
                "parameters": {"name": name},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def command_messages(*, sequence: int, correlation: str, command_id: str, name: str) -> list[str]:
    fingerprint = command_fingerprint(name)
    return [
        message(
            sequence,
            MessageType.COMMAND_ACCEPTED,
            CommandAcceptedPayload(command_id=command_id, action_fingerprint=fingerprint),
            correlation_id=correlation,
        ),
        message(
            sequence + 1,
            MessageType.COMMAND_COMPLETED,
            CommandCompletedPayload(
                command_id=command_id,
                action_fingerprint=fingerprint,
                before_name="Fixture Transport",
                after_name=name,
                state_changed=True,
                cost=0,
            ),
            correlation_id=correlation,
        ),
    ]
