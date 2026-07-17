from __future__ import annotations

import hashlib
import json
from collections import deque

from sim_pilot.openttd.gamescript.messages import (
    BridgeCapabilities,
    BridgeCompanySnapshot,
    BridgeMessage,
    BridgeSnapshot,
    CommandAcceptedPayload,
    CommandCompletedPayload,
    HelloPayload,
    MessageType,
    ResyncResponsePayload,
)
from sim_pilot.openttd.models import OpenTTDConnectionMetadata


def capabilities() -> BridgeCapabilities:
    return BridgeCapabilities(
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
