"""Stateful client for the production OpenTTD GameScript bridge."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sim_pilot.openttd.gamescript.errors import (
    BridgeCommandError,
    BridgeIncompatibleError,
    BridgeSequenceError,
    BridgeUnavailableError,
)
from sim_pilot.openttd.gamescript.messages import (
    ADMIN_TO_GAMESCRIPT_MAX_BYTES,
    BRIDGE_PROTOCOL_VERSION,
    BridgeCapabilities,
    BridgeCargoEntity,
    BridgeCompanyEntity,
    BridgeErrorPayload,
    BridgeIndustryEntity,
    BridgeMessage,
    BridgeOrderEntity,
    BridgeSnapshot,
    BridgeStationEntity,
    BridgeTownEntity,
    BridgeVehicleEntity,
    CommandAcceptedPayload,
    CommandCompletedPayload,
    CommandRequestPayload,
    HelloPayload,
    MessageType,
    ResyncRequestPayload,
    SetCompanyNameParameters,
    WorldCollection,
    WorldCollectionPagePayload,
    WorldManifestPayload,
    WorldSnapshotCompletePayload,
    parse_bridge_message,
)
from sim_pilot.openttd.gamescript.models import (
    BridgeHealth,
    BridgeWorldSnapshot,
    SynchronizationState,
)
from sim_pilot.openttd.models import OpenTTDConnectionMetadata


class GameScriptAdminTransport(Protocol):
    @property
    def metadata(self) -> OpenTTDConnectionMetadata: ...

    async def connect(self) -> None: ...

    async def subscribe_gamescript(self) -> None: ...

    async def send_gamescript(self, value: str) -> None: ...

    async def receive_gamescript(self, timeout: float | None = None) -> str: ...

    async def reconnect(self) -> None: ...

    async def close(self) -> None: ...


class GameScriptBridgeClient:
    """Negotiate, synchronize, and correlate one bridge over one Admin transport."""

    def __init__(
        self,
        transport: GameScriptAdminTransport,
        *,
        company_id: int,
        allow_writes: bool = False,
        timeout_seconds: float = 5.0,
        prior_health: BridgeHealth | None = None,
        reject_instance_change: bool = False,
    ) -> None:
        self.transport = transport
        self.company_id = company_id
        self.allow_writes = allow_writes
        self.timeout_seconds = timeout_seconds
        self.health = prior_health or BridgeHealth.disconnected()
        self._outgoing_sequence = 0
        self._seen_message_ids: set[str] = set()
        self._hello: HelloPayload | None = None
        self._world_manifest: WorldManifestPayload | None = None
        self._world_pages: dict[WorldCollection, dict[int, WorldCollectionPagePayload]] = {}
        self._reject_instance_change = reject_instance_change

    async def synchronize(self, *, reason: str = "connect") -> BridgeHealth:
        self._set_state(SynchronizationState.CONNECTING)
        try:
            await self.transport.connect()
            await self.transport.subscribe_gamescript()
            # Save/load can roll the script sequence back to the saved boundary.
            # A correlated full resync establishes a new delivery-dedup window;
            # durable command deduplication remains in the GameScript ledger.
            self._seen_message_ids.clear()
            self._set_state(SynchronizationState.AWAITING_HELLO, connected=True)
            request_id = await self._send(
                MessageType.RESYNC_REQUEST,
                ResyncRequestPayload(
                    last_script_instance_id=self.health.script_instance_id,
                    last_sequence=self.health.last_sequence,
                    reason=reason,
                ),
                company_id=self.company_id,
            )
            self._set_state(SynchronizationState.RESYNCHRONIZING)
            got_hello = False
            got_capabilities = False
            got_response = False
            got_snapshot = False
            got_world = False
            while True:
                message = await self._receive(allow_resync_baseline=True)
                if message.message_type is MessageType.HELLO:
                    self._accept_hello(message)
                    got_hello = True
                    self._set_state(SynchronizationState.AWAITING_CAPABILITIES)
                elif message.message_type is MessageType.CAPABILITIES:
                    self._accept_capabilities(message)
                    got_capabilities = True
                    self._set_state(SynchronizationState.AWAITING_SNAPSHOT)
                elif (
                    message.message_type is MessageType.RESYNC_RESPONSE
                    and message.correlation_id == request_id
                ):
                    got_response = True
                elif message.message_type is MessageType.STATE_SNAPSHOT:
                    self._accept_snapshot(message)
                    got_snapshot = True
                elif message.message_type is MessageType.WORLD_MANIFEST:
                    if got_hello and got_capabilities and got_response and got_snapshot:
                        self._accept_world_manifest(message)
                elif message.message_type is MessageType.WORLD_COLLECTION_PAGE:
                    if (
                        got_hello
                        and got_capabilities
                        and got_response
                        and got_snapshot
                        and self._world_manifest is not None
                    ):
                        self._accept_world_page(message)
                elif message.message_type is MessageType.WORLD_SNAPSHOT_COMPLETE:
                    if (
                        got_hello
                        and got_capabilities
                        and got_response
                        and got_snapshot
                        and self._world_manifest is not None
                    ):
                        self._accept_world_complete(message)
                        got_world = True
                needs_world = bool(
                    self.health.capabilities is not None
                    and self.health.capabilities.world_snapshots
                )
                if (
                    got_hello
                    and got_capabilities
                    and got_response
                    and got_snapshot
                    and (got_world or not needs_world)
                ):
                    self._set_state(SynchronizationState.SYNCHRONIZED)
                    return self.health
        except BridgeIncompatibleError:
            self._set_state(SynchronizationState.INCOMPATIBLE)
            raise
        except Exception as error:
            self._set_state(SynchronizationState.FAILED, degraded_reason=str(error))
            raise

    async def refresh_snapshot(self) -> BridgeSnapshot:
        health = await self.synchronize(reason="snapshot_refresh")
        if health.snapshot is None:
            raise BridgeUnavailableError("bridge synchronization returned no snapshot")
        return health.snapshot

    async def verify_identity(self) -> BridgeHealth:
        """Correlate bridge identity without waiting for paginated world collections."""
        self._set_state(SynchronizationState.CONNECTING)
        try:
            await self.transport.connect()
            await self.transport.subscribe_gamescript()
            self._seen_message_ids.clear()
            self._set_state(SynchronizationState.AWAITING_HELLO, connected=True)
            request_id = await self._send(
                MessageType.RESYNC_REQUEST,
                ResyncRequestPayload(
                    last_script_instance_id=self.health.script_instance_id,
                    last_sequence=self.health.last_sequence,
                    reason="identity_probe",
                ),
                company_id=self.company_id,
            )
            self._set_state(SynchronizationState.RESYNCHRONIZING)
            got_hello = False
            got_capabilities = False
            got_response = False
            got_snapshot = False
            while not (got_hello and got_capabilities and got_response and got_snapshot):
                message = await self._receive(allow_resync_baseline=True)
                if message.message_type is MessageType.HELLO:
                    self._accept_hello(message)
                    got_hello = True
                elif message.message_type is MessageType.CAPABILITIES:
                    self._accept_capabilities(message)
                    got_capabilities = True
                elif (
                    message.message_type is MessageType.RESYNC_RESPONSE
                    and message.correlation_id == request_id
                ):
                    got_response = True
                elif message.message_type is MessageType.STATE_SNAPSHOT:
                    self._accept_snapshot(message)
                    got_snapshot = True
            self._set_state(SynchronizationState.IDENTITY_VERIFIED)
            return self.health
        except BridgeIncompatibleError:
            self._set_state(SynchronizationState.INCOMPATIBLE)
            raise
        except Exception as error:
            self._set_state(SynchronizationState.FAILED, degraded_reason=str(error))
            raise

    async def execute_set_company_name(
        self,
        *,
        name: str,
        prior_snapshot_id: str,
        command_id: str | None = None,
        request_timestamp: datetime | None = None,
    ) -> tuple[CommandCompletedPayload, BridgeSnapshot]:
        if not self.allow_writes:
            raise BridgeCommandError("GameScript writes require explicit opt-in")
        capabilities = self.health.capabilities
        if capabilities is None or "set_company_name" not in capabilities.supported_actions:
            raise BridgeCommandError("running bridge does not advertise set_company_name")
        if self.health.synchronization_state is not SynchronizationState.SYNCHRONIZED:
            raise BridgeCommandError("bridge must be synchronized before a command")
        stable_command_id = command_id or str(uuid4())
        parameters = SetCompanyNameParameters(name=name)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "action": "set_company_name",
                    "company_id": self.company_id,
                    "parameters": parameters.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        request_id = await self._send(
            MessageType.COMMAND_REQUEST,
            CommandRequestPayload(
                command_id=stable_command_id,
                parameters=parameters,
                action_fingerprint=fingerprint,
                expected_capability_fingerprint=capabilities.fingerprint,
                expected_company_id=self.company_id,
                prior_snapshot_id=prior_snapshot_id,
                request_timestamp=(request_timestamp or datetime.now(UTC)).isoformat(),
            ),
            company_id=self.company_id,
        )
        accepted = False
        while True:
            message = await self._receive()
            if message.correlation_id != request_id:
                self._consume_unsolicited(message)
                continue
            if message.message_type is MessageType.COMMAND_ACCEPTED:
                if not isinstance(message.payload, CommandAcceptedPayload):
                    raise BridgeCommandError("invalid command acceptance payload")
                accepted = True
                continue
            if message.message_type in {
                MessageType.COMMAND_REJECTED,
                MessageType.COMMAND_FAILED,
                MessageType.ERROR,
            }:
                if not isinstance(message.payload, BridgeErrorPayload):
                    raise BridgeCommandError("invalid command failure payload")
                raise BridgeCommandError(f"{message.payload.code.value}: {message.payload.message}")
            if message.message_type is MessageType.COMMAND_COMPLETED:
                if not accepted:
                    raise BridgeCommandError("command completed before acceptance")
                if not isinstance(message.payload, CommandCompletedPayload):
                    raise BridgeCommandError("invalid command completion payload")
                completed = message.payload
                snapshot = await self.refresh_snapshot()
                if snapshot.company is None or snapshot.company.name != name:
                    raise BridgeCommandError(
                        "command completed but fresh snapshot did not verify company name"
                    )
                return completed, snapshot

    async def reconnect(self) -> BridgeHealth:
        await self.transport.reconnect()
        return await self.synchronize(reason="admin_reconnect")

    async def close(self) -> None:
        await self.transport.close()
        self.health = self.health.model_copy(
            update={
                "connected": False,
                "authenticated": False,
                "synchronization_state": SynchronizationState.DISCONNECTED,
            }
        )

    async def _send(
        self,
        message_type: MessageType,
        payload: object,
        *,
        company_id: int | None = None,
    ) -> str:
        self._outgoing_sequence += 1
        message_id = f"sim-pilot:{uuid4()}"
        message = BridgeMessage.model_validate(
            {
                "sequence": self._outgoing_sequence,
                "message_id": message_id,
                "script_instance_id": self.health.script_instance_id or "unknown",
                "message_type": message_type,
                "game_date": 0,
                "company_id": company_id,
                "payload": payload,
            },
            strict=True,
        )
        await self.transport.send_gamescript(
            message.to_json(maximum_bytes=ADMIN_TO_GAMESCRIPT_MAX_BYTES)
        )
        return message_id

    async def _receive(self, *, allow_resync_baseline: bool = False) -> BridgeMessage:
        raw = await self.transport.receive_gamescript(self.timeout_seconds)
        try:
            message = parse_bridge_message(raw)
        except ValueError as error:
            raise BridgeIncompatibleError(f"invalid bridge message: {error}") from error
        if message.protocol_version not in {1, BRIDGE_PROTOCOL_VERSION}:
            raise BridgeIncompatibleError(f"unsupported bridge protocol {message.protocol_version}")
        if message.message_id in self._seen_message_ids:
            raise BridgeSequenceError(f"duplicate bridge message {message.message_id}")
        prior_instance = self.health.script_instance_id
        prior_sequence = self.health.last_sequence
        if prior_instance is not None and message.script_instance_id != prior_instance:
            if self._reject_instance_change:
                raise BridgeSequenceError(
                    "script identity changed; refusing to resume against a different game"
                )
            if not allow_resync_baseline:
                raise BridgeSequenceError("script instance changed outside resynchronization")
            prior_sequence = None
            self._seen_message_ids.clear()
        if (
            prior_sequence is not None
            and message.script_instance_id == prior_instance
            and message.sequence != prior_sequence + 1
            and not allow_resync_baseline
        ):
            raise BridgeSequenceError(
                f"bridge sequence gap: expected {prior_sequence + 1}, received {message.sequence}"
            )
        self._seen_message_ids.add(message.message_id)
        self.health = self.health.model_copy(
            update={
                "connected": True,
                "authenticated": True,
                "bridge_detected": True,
                "bridge_protocol_version": message.protocol_version,
                "script_instance_id": message.script_instance_id,
                "last_sequence": message.sequence,
                "active_company_context": message.company_id,
            }
        )
        if message.message_type is MessageType.HEARTBEAT:
            self.health = self.health.model_copy(update={"last_heartbeat": datetime.now(UTC)})
        return message

    def _accept_hello(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, HelloPayload):
            raise BridgeIncompatibleError("hello payload has the wrong schema")
        hello = message.payload
        if hello.openttd_version != self.transport.metadata.openttd_version:
            raise BridgeIncompatibleError(
                "GameScript target version does not match connected OpenTTD"
            )
        self._hello = hello
        self.health = self.health.model_copy(
            update={
                "openttd_version": hello.openttd_version,
                "script_version": hello.script_version,
            }
        )

    def _accept_capabilities(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, BridgeCapabilities):
            raise BridgeIncompatibleError("capabilities payload has the wrong schema")
        self.health = self.health.model_copy(
            update={
                "capabilities": message.payload,
                "capability_fingerprint": message.payload.fingerprint,
            }
        )

    def _accept_snapshot(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, BridgeSnapshot):
            raise BridgeIncompatibleError("snapshot payload has the wrong schema")
        self.health = self.health.model_copy(
            update={
                "snapshot": message.payload,
                "last_snapshot_at": datetime.now(UTC),
                "active_company_context": (
                    None if message.payload.company is None else message.payload.company.company_id
                ),
            }
        )

    def _accept_world_manifest(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, WorldManifestPayload):
            raise BridgeIncompatibleError("world manifest payload has the wrong schema")
        self._world_manifest = message.payload
        self._world_pages = {}

    def _accept_world_page(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, WorldCollectionPagePayload):
            raise BridgeIncompatibleError("world collection page has the wrong schema")
        manifest = self._world_manifest
        page = message.payload
        if manifest is None or page.snapshot_id != manifest.snapshot_id:
            raise BridgeSequenceError("world page does not match the active manifest")
        pages = self._world_pages.setdefault(page.collection, {})
        if page.page_index in pages:
            raise BridgeSequenceError("duplicate world collection page")
        if page.page_index >= page.page_count:
            raise BridgeSequenceError("world collection page index is out of range")
        pages[page.page_index] = page

    def _accept_world_complete(self, message: BridgeMessage) -> None:
        if not isinstance(message.payload, WorldSnapshotCompletePayload):
            raise BridgeIncompatibleError("world completion payload has the wrong schema")
        manifest = self._world_manifest
        completed = message.payload
        if manifest is None or completed.snapshot_id != manifest.snapshot_id:
            raise BridgeSequenceError("world completion does not match the active manifest")
        entities: dict[WorldCollection, list[object]] = {
            collection: [] for collection in WorldCollection
        }
        for collection in WorldCollection:
            expected = manifest.collection_counts.get(collection.value, 0)
            pages = self._world_pages.get(collection, {})
            expected_pages = (
                0 if expected == 0 else next(iter(pages.values())).page_count if pages else 0
            )
            if expected_pages != len(pages) or set(pages) != set(range(expected_pages)):
                raise BridgeSequenceError(f"incomplete {collection.value} world pages")
            for index in range(expected_pages):
                entities[collection].extend(pages[index].items)
            if len(entities[collection]) != expected:
                raise BridgeSequenceError(f"{collection.value} count does not match manifest")
        total = sum(len(items) for items in entities.values())
        if total != completed.total_items:
            raise BridgeSequenceError("world completion item count does not match pages")
        self.health = self.health.model_copy(
            update={
                "world_snapshot": BridgeWorldSnapshot(
                    snapshot_id=completed.snapshot_id,
                    capture_started_game_date=manifest.capture_started_game_date,
                    capture_completed_game_date=completed.capture_completed_game_date,
                    companies=tuple(
                        item
                        for item in entities[WorldCollection.COMPANIES]
                        if isinstance(item, BridgeCompanyEntity)
                    ),
                    towns=tuple(
                        item
                        for item in entities[WorldCollection.TOWNS]
                        if isinstance(item, BridgeTownEntity)
                    ),
                    industries=tuple(
                        item
                        for item in entities[WorldCollection.INDUSTRIES]
                        if isinstance(item, BridgeIndustryEntity)
                    ),
                    stations=tuple(
                        item
                        for item in entities[WorldCollection.STATIONS]
                        if isinstance(item, BridgeStationEntity)
                    ),
                    vehicles=tuple(
                        item
                        for item in entities[WorldCollection.VEHICLES]
                        if isinstance(item, BridgeVehicleEntity)
                    ),
                    orders=tuple(
                        item
                        for item in entities[WorldCollection.ORDERS]
                        if isinstance(item, BridgeOrderEntity)
                    ),
                    cargos=tuple(
                        item
                        for item in entities[WorldCollection.CARGOS]
                        if isinstance(item, BridgeCargoEntity)
                    ),
                )
            }
        )

    def _consume_unsolicited(self, message: BridgeMessage) -> None:
        if message.message_type is MessageType.HEARTBEAT:
            return
        if message.message_type is MessageType.STATE_SNAPSHOT:
            self._accept_snapshot(message)
        elif message.message_type is MessageType.WORLD_MANIFEST:
            self._accept_world_manifest(message)
        elif message.message_type is MessageType.WORLD_COLLECTION_PAGE:
            self._accept_world_page(message)
        elif message.message_type is MessageType.WORLD_SNAPSHOT_COMPLETE:
            self._accept_world_complete(message)

    def _set_state(
        self,
        state: SynchronizationState,
        *,
        connected: bool | None = None,
        degraded_reason: str | None = None,
    ) -> None:
        self.health = self.health.model_copy(
            update={
                "synchronization_state": state,
                "connected": self.health.connected if connected is None else connected,
                "authenticated": self.health.authenticated if connected is None else connected,
                "degraded_reason": degraded_reason,
            }
        )
