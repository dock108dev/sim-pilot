"""Authenticated length-prefixed loopback client for read-only protocol v3."""

from __future__ import annotations

import asyncio
import ipaddress
import struct
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from sim_pilot.game_bridge.errors import (
    GameBridgeAuthenticationError,
    GameBridgeConnectionError,
    GameBridgeIncompatibleError,
    GameBridgeMessageSizeError,
    GameBridgeProtocolError,
    GameBridgeSequenceError,
    GameBridgeSnapshotError,
    GameBridgeTimeoutError,
)
from sim_pilot.game_bridge.models import (
    DEFAULT_MAXIMUM_MESSAGE_BYTES,
    Architecture,
    BridgeEnvelope,
    BridgeHelloPayload,
    CapabilityManifestPayload,
    ClientHelloPayload,
    FullSnapshotRequestPayload,
    FullSnapshotResponsePayload,
    GameSnapshot,
    HeartbeatPayload,
    Identity,
    IdentityStatus,
    MessageType,
    Platform,
    ProtocolErrorPayload,
    ResynchronizationRequestPayload,
    parse_envelope,
)

_FRAME_HEADER = struct.Struct(">I")


class ClientState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    SYNCHRONIZED = "synchronized"
    RESYNCHRONIZING = "resynchronizing"
    FAILED = "failed"


class GameBridgeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    authentication_token: SecretStr
    expected_adapter_version: str = Field(min_length=1, max_length=128)
    expected_game_id: str = Field(min_length=1, max_length=128)
    expected_game_version: str = Field(min_length=1, max_length=128)
    platform: Platform
    architecture: Architecture
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    maximum_message_bytes: int = Field(
        default=DEFAULT_MAXIMUM_MESSAGE_BYTES, ge=1024, le=16_777_216
    )

    @model_validator(mode="after")
    def require_loopback(self) -> GameBridgeConfiguration:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as error:
            raise ValueError("game bridge host must be an explicit loopback IP address") from error
        if not address.is_loopback:
            raise ValueError("game bridge host must be loopback")
        if len(self.authentication_token.get_secret_value()) < 32:
            raise ValueError("game bridge authentication token must contain at least 32 characters")
        return self


class GameBridgeClient:
    """Own one authenticated bridge connection and enforce its delivery timeline."""

    def __init__(self, configuration: GameBridgeConfiguration) -> None:
        self.configuration = configuration
        self.state = ClientState.DISCONNECTED
        self.capabilities: CapabilityManifestPayload | None = None
        self.bridge_instance_id: str | None = None
        self.game_session_id: str | None = None
        self.map_identity: Identity | None = None
        self.save_identity: Identity | None = None
        self.last_bridge_sequence: int | None = None
        self.last_heartbeat_at: datetime | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._outgoing_sequence = 0
        self._seen_message_ids: set[str] = set()
        self._client_instance_id = str(uuid4())

    async def connect(self) -> CapabilityManifestPayload:
        if self.state is ClientState.SYNCHRONIZED and self.capabilities is not None:
            return self.capabilities
        self.state = ClientState.CONNECTING
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.configuration.host, self.configuration.port),
                timeout=self.configuration.connect_timeout_seconds,
            )
            self.state = ClientState.AUTHENTICATING
            request = await self._send(
                MessageType.CLIENT_HELLO,
                ClientHelloPayload(
                    authentication_token=self.configuration.authentication_token.get_secret_value(),
                    client_instance_id=self._client_instance_id,
                    expected_adapter_version=self.configuration.expected_adapter_version,
                    expected_game_id=self.configuration.expected_game_id,
                    expected_game_version=self.configuration.expected_game_version,
                ),
            )
            hello = await self._receive(allow_identity_baseline=True)
            if hello.message_type is MessageType.AUTHENTICATION_FAILURE:
                raise GameBridgeAuthenticationError("game bridge authentication failed")
            if hello.message_type is not MessageType.BRIDGE_HELLO:
                raise GameBridgeProtocolError(
                    "bridge hello must be the first authenticated response"
                )
            if hello.correlation_id != request.message_id:
                raise GameBridgeProtocolError(
                    "bridge hello correlation does not match client hello"
                )
            if not isinstance(hello.payload, BridgeHelloPayload):
                raise GameBridgeProtocolError("bridge hello payload has the wrong schema")
            manifest = await self._receive()
            if manifest.message_type is not MessageType.CAPABILITY_MANIFEST:
                raise GameBridgeProtocolError("capability manifest must follow bridge hello")
            if not isinstance(manifest.payload, CapabilityManifestPayload):
                raise GameBridgeProtocolError("capability manifest payload has the wrong schema")
            self.capabilities = manifest.payload
            self.state = ClientState.SYNCHRONIZED
            return manifest.payload
        except GameBridgeAuthenticationError:
            self.state = ClientState.FAILED
            await self.close()
            raise
        except TimeoutError as error:
            self.state = ClientState.FAILED
            await self.close()
            raise GameBridgeTimeoutError("timed out connecting to the game bridge") from error
        except (ConnectionRefusedError, OSError) as error:
            self.state = ClientState.FAILED
            await self.close()
            raise GameBridgeConnectionError(
                "could not connect to the loopback game bridge"
            ) from error
        except Exception:
            self.state = ClientState.FAILED
            await self.close()
            raise

    async def request_full_snapshot(self) -> GameSnapshot:
        if self.state is not ClientState.SYNCHRONIZED:
            raise GameBridgeProtocolError("bridge must be synchronized before snapshot request")
        if self.bridge_instance_id is None or self.game_session_id is None:
            raise GameBridgeProtocolError("bridge identity is unavailable")
        request = await self._send(
            MessageType.FULL_SNAPSHOT_REQUEST,
            FullSnapshotRequestPayload(
                expected_bridge_instance_id=self.bridge_instance_id,
                expected_game_session_id=self.game_session_id,
            ),
        )
        while True:
            response = await self._receive()
            if response.message_type is MessageType.HEARTBEAT:
                continue
            if response.message_type is MessageType.PROTOCOL_ERROR:
                self._raise_protocol_error(response)
            if response.message_type is not MessageType.FULL_SNAPSHOT_RESPONSE:
                raise GameBridgeProtocolError("unexpected message while awaiting full snapshot")
            if response.correlation_id != request.message_id:
                raise GameBridgeProtocolError("snapshot correlation does not match request")
            if not isinstance(response.payload, FullSnapshotResponsePayload):
                raise GameBridgeProtocolError("snapshot response payload has the wrong schema")
            self._validate_snapshot(response, response.payload.snapshot)
            return response.payload.snapshot

    async def resynchronize(self, *, reason: str) -> CapabilityManifestPayload:
        if self._writer is None:
            return await self.connect()
        self.state = ClientState.RESYNCHRONIZING
        request = await self._send(
            MessageType.RESYNCHRONIZATION_REQUEST,
            ResynchronizationRequestPayload(
                last_bridge_instance_id=self.bridge_instance_id,
                last_game_session_id=self.game_session_id,
                last_bridge_sequence=self.last_bridge_sequence,
                reason=reason,
            ),
        )
        self._seen_message_ids.clear()
        hello = await self._receive(allow_identity_baseline=True)
        if hello.message_type is not MessageType.BRIDGE_HELLO:
            raise GameBridgeProtocolError("resynchronization requires a fresh bridge hello")
        if hello.correlation_id != request.message_id:
            raise GameBridgeProtocolError("resynchronization hello correlation mismatch")
        manifest = await self._receive()
        if manifest.message_type is not MessageType.CAPABILITY_MANIFEST or not isinstance(
            manifest.payload, CapabilityManifestPayload
        ):
            raise GameBridgeProtocolError("resynchronization requires a capability manifest")
        self.capabilities = manifest.payload
        self.state = ClientState.SYNCHRONIZED
        return manifest.payload

    async def close(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
        self.state = ClientState.DISCONNECTED

    async def _send(self, message_type: MessageType, payload: object) -> BridgeEnvelope:
        writer = self._writer
        if writer is None:
            raise GameBridgeConnectionError("game bridge is disconnected")
        self._outgoing_sequence += 1
        envelope = BridgeEnvelope.model_validate(
            {
                "adapter_version": self.configuration.expected_adapter_version,
                "game_id": self.configuration.expected_game_id,
                "game_version": self.configuration.expected_game_version,
                "platform": self.configuration.platform,
                "architecture": self.configuration.architecture,
                "bridge_instance_id": self.bridge_instance_id or "client-unnegotiated",
                "game_session_id": self.game_session_id or "client-unnegotiated",
                "map_identity": self.map_identity
                or Identity(status=IdentityStatus.UNAVAILABLE, detail="not negotiated"),
                "save_identity": self.save_identity
                or Identity(status=IdentityStatus.UNAVAILABLE, detail="not negotiated"),
                "message_id": f"client:{uuid4()}",
                "bridge_sequence": self._outgoing_sequence,
                "message_type": message_type,
                "timestamp": datetime.now(UTC),
                "payload": payload,
            },
            strict=True,
        )
        try:
            body = envelope.to_json(maximum_bytes=self.configuration.maximum_message_bytes)
        except ValueError as error:
            raise GameBridgeMessageSizeError(str(error)) from error
        writer.write(_FRAME_HEADER.pack(len(body)) + body)
        try:
            await asyncio.wait_for(writer.drain(), timeout=self.configuration.read_timeout_seconds)
        except TimeoutError as error:
            raise GameBridgeTimeoutError("timed out writing to the game bridge") from error
        return envelope

    async def _receive(self, *, allow_identity_baseline: bool = False) -> BridgeEnvelope:
        body = await self._read_frame()
        try:
            message = parse_envelope(body, maximum_bytes=self.configuration.maximum_message_bytes)
        except ValueError as error:
            raise GameBridgeProtocolError(f"invalid bridge envelope: {error}") from error
        self._validate_compatibility(message)
        if message.message_id in self._seen_message_ids:
            raise GameBridgeSequenceError(f"duplicate bridge message {message.message_id}")
        if allow_identity_baseline:
            self._seen_message_ids.clear()
        else:
            if self.bridge_instance_id is not None and (
                message.bridge_instance_id != self.bridge_instance_id
            ):
                raise GameBridgeSequenceError("bridge instance changed outside resynchronization")
            if self.game_session_id is not None and (
                message.game_session_id != self.game_session_id
            ):
                raise GameBridgeSequenceError("game session changed outside resynchronization")
            if self.map_identity is not None and message.map_identity != self.map_identity:
                raise GameBridgeSequenceError("map identity changed outside resynchronization")
            if self.save_identity is not None and message.save_identity != self.save_identity:
                raise GameBridgeSequenceError("save identity changed outside resynchronization")
            if self.last_bridge_sequence is not None and (
                message.bridge_sequence != self.last_bridge_sequence + 1
            ):
                raise GameBridgeSequenceError(
                    f"bridge sequence gap: expected {self.last_bridge_sequence + 1}, "
                    f"received {message.bridge_sequence}"
                )
        self._seen_message_ids.add(message.message_id)
        self.bridge_instance_id = message.bridge_instance_id
        self.game_session_id = message.game_session_id
        self.map_identity = message.map_identity
        self.save_identity = message.save_identity
        self.last_bridge_sequence = message.bridge_sequence
        if message.message_type is MessageType.HEARTBEAT:
            if not isinstance(message.payload, HeartbeatPayload):
                raise GameBridgeProtocolError("heartbeat payload has the wrong schema")
            self.last_heartbeat_at = datetime.now(UTC)
        return message

    async def _read_frame(self) -> bytes:
        reader = self._reader
        if reader is None:
            raise GameBridgeConnectionError("game bridge is disconnected")
        try:
            header = await asyncio.wait_for(
                reader.readexactly(_FRAME_HEADER.size),
                timeout=self.configuration.read_timeout_seconds,
            )
            size = _FRAME_HEADER.unpack(header)[0]
            if size == 0 or size > self.configuration.maximum_message_bytes:
                raise GameBridgeMessageSizeError(
                    f"bridge frame length {size} is outside the supported range"
                )
            return await asyncio.wait_for(
                reader.readexactly(size), timeout=self.configuration.read_timeout_seconds
            )
        except TimeoutError as error:
            raise GameBridgeTimeoutError("timed out reading from the game bridge") from error
        except asyncio.IncompleteReadError as error:
            raise GameBridgeConnectionError("game bridge disconnected mid-frame") from error

    def _validate_compatibility(self, message: BridgeEnvelope) -> None:
        expected = self.configuration
        if message.adapter_version != expected.expected_adapter_version:
            raise GameBridgeIncompatibleError("bridge adapter version is incompatible")
        if message.game_id != expected.expected_game_id:
            raise GameBridgeIncompatibleError("bridge game identity is incompatible")
        if message.game_version != expected.expected_game_version:
            raise GameBridgeIncompatibleError("bridge game version is incompatible")
        if (
            message.platform is not expected.platform
            or message.architecture is not expected.architecture
        ):
            raise GameBridgeIncompatibleError("bridge platform or architecture is incompatible")

    def _validate_snapshot(self, message: BridgeEnvelope, snapshot: GameSnapshot) -> None:
        matches = (
            snapshot.bridge_sequence == message.bridge_sequence
            and snapshot.bridge_instance_id == message.bridge_instance_id
            and snapshot.game_session_id == message.game_session_id
            and snapshot.game_id == message.game_id
            and snapshot.game_version == message.game_version
            and snapshot.adapter_version == message.adapter_version
            and snapshot.platform is message.platform
            and snapshot.architecture is message.architecture
            and snapshot.map_identity == message.map_identity
            and snapshot.save_identity == message.save_identity
        )
        if not matches:
            raise GameBridgeSnapshotError("snapshot metadata does not match its bridge envelope")

    @staticmethod
    def _raise_protocol_error(message: BridgeEnvelope) -> None:
        if not isinstance(message.payload, ProtocolErrorPayload):
            raise GameBridgeProtocolError("protocol error payload has the wrong schema")
        raise GameBridgeProtocolError(f"{message.payload.code.value}: {message.payload.message}")
