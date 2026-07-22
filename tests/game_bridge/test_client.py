from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from sim_pilot.game_bridge.client import ClientState, GameBridgeClient, GameBridgeConfiguration
from sim_pilot.game_bridge.errors import (
    GameBridgeAuthenticationError,
    GameBridgeIncompatibleError,
    GameBridgeMessageSizeError,
    GameBridgeSequenceError,
)
from sim_pilot.game_bridge.models import Architecture, BridgeEnvelope, MessageType, Platform

FIXTURES = Path(__file__).parents[1] / "fixtures" / "game_bridge" / "v2"
Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


def bridge_hello_value() -> dict[str, object]:
    value = json.loads((FIXTURES / "bridge_hello.json").read_text())
    value["protocol_version"] = 3
    value["adapter_version"] = "rail-route-ui-observer-v1"
    value["payload"]["negotiated_protocol_version"] = 3
    return value


def configuration(port: int) -> GameBridgeConfiguration:
    return GameBridgeConfiguration(
        port=port,
        authentication_token=SecretStr("test-token-000000000000000000000"),
        expected_adapter_version="rail-route-ui-observer-v1",
        expected_game_id="rail-route",
        expected_game_version="2.3.24",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        read_timeout_seconds=0.5,
    )


async def read_frame(reader: asyncio.StreamReader) -> BridgeEnvelope:
    size = struct.unpack(">I", await reader.readexactly(4))[0]
    return BridgeEnvelope.model_validate_json(await reader.readexactly(size), strict=True)


async def send_fixture(
    writer: asyncio.StreamWriter,
    name: str,
    *,
    correlation_id: str | None = None,
    sequence: int | None = None,
    message_id: str | None = None,
    game_session_id: str | None = None,
    snapshot_sequence: int | None = None,
) -> None:
    value = json.loads((FIXTURES / name).read_text())
    value["protocol_version"] = 3
    value["adapter_version"] = "rail-route-ui-observer-v1"
    if name == "bridge_hello.json":
        value["payload"]["negotiated_protocol_version"] = 3
    elif name == "capability_manifest.json":
        value["payload"]["gameplay_actions"] = []
    elif name == "full_snapshot_response.json":
        value["payload"]["snapshot"]["adapter_version"] = "rail-route-ui-observer-v1"
    if correlation_id is not None:
        value["correlation_id"] = correlation_id
    if sequence is not None:
        value["bridge_sequence"] = sequence
    if message_id is not None:
        value["message_id"] = message_id
    if game_session_id is not None:
        value["game_session_id"] = game_session_id
    if snapshot_sequence is not None:
        value["payload"]["snapshot"]["bridge_sequence"] = snapshot_sequence
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    writer.write(struct.pack(">I", len(body)) + body)
    await writer.drain()


async def run_server(handler: Handler) -> tuple[asyncio.AbstractServer, int]:
    async def closing_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await handler(reader, writer)
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(closing_handler, "127.0.0.1", 0)
    socket = server.sockets[0]
    return server, int(socket.getsockname()[1])


def test_loopback_configuration_rejects_remote_or_named_hosts_and_short_tokens() -> None:
    for host in ("192.0.2.1", "localhost"):
        with pytest.raises(ValidationError, match="loopback"):
            GameBridgeConfiguration(
                host=host,
                port=1,
                authentication_token=SecretStr("x" * 32),
                expected_adapter_version="adapter-v1",
                expected_game_id="game",
                expected_game_version="1",
                platform=Platform.MACOS,
                architecture=Architecture.ARM64,
            )
    with pytest.raises(ValidationError, match="32"):
        GameBridgeConfiguration(
            port=1,
            authentication_token=SecretStr("short"),
            expected_adapter_version="adapter-v1",
            expected_game_id="game",
            expected_game_version="1",
            platform=Platform.MACOS,
            architecture=Architecture.ARM64,
        )


def test_authenticated_handshake_snapshot_and_clean_disconnect() -> None:
    async def scenario() -> tuple[GameBridgeClient, BridgeEnvelope]:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            await send_fixture(writer, "bridge_hello.json", correlation_id=hello.message_id)
            await send_fixture(writer, "capability_manifest.json")
            request = await read_frame(reader)
            assert request.message_type is MessageType.FULL_SNAPSHOT_REQUEST
            await send_fixture(
                writer, "full_snapshot_response.json", correlation_id=request.message_id
            )

        server, port = await run_server(handler)
        async with server:
            client = GameBridgeClient(configuration(port))
            capabilities = await client.connect()
            assert capabilities.gameplay_actions == ()
            snapshot = await client.request_full_snapshot()
            assert snapshot.game_state == {"paused": True, "simulation_speed": 0}
            await client.close()
            return client, BridgeEnvelope.model_validate_json(
                json.dumps(bridge_hello_value()).encode(),
                strict=True,
            )

    client, _ = asyncio.run(scenario())
    assert client.state is ClientState.DISCONNECTED


def test_authentication_failure_closes_connection_without_exposing_token() -> None:
    async def scenario() -> GameBridgeClient:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            raw = bridge_hello_value()
            raw["message_type"] = "authentication_failure"
            raw["payload"] = {"reason": "authentication_failed"}
            raw["correlation_id"] = hello.message_id
            body = json.dumps(raw).encode()
            writer.write(struct.pack(">I", len(body)) + body)
            await writer.drain()

        server, port = await run_server(handler)
        async with server:
            client = GameBridgeClient(configuration(port))
            with pytest.raises(GameBridgeAuthenticationError) as captured:
                await client.connect()
            assert "test-token" not in str(captured.value)
            return client

    client = asyncio.run(scenario())
    assert client.state is ClientState.DISCONNECTED


def test_incompatible_adapter_duplicate_and_sequence_gap_fail_closed() -> None:
    async def incompatible() -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            raw = bridge_hello_value()
            raw["adapter_version"] = "wrong-adapter"
            raw["correlation_id"] = hello.message_id
            body = json.dumps(raw).encode()
            writer.write(struct.pack(">I", len(body)) + body)
            await writer.drain()

        server, port = await run_server(handler)
        async with server:
            with pytest.raises(GameBridgeIncompatibleError):
                await GameBridgeClient(configuration(port)).connect()

    asyncio.run(incompatible())

    async def ordering(*, duplicate: bool) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            await send_fixture(writer, "bridge_hello.json", correlation_id=hello.message_id)
            await send_fixture(
                writer,
                "capability_manifest.json",
                sequence=1 if duplicate else 3,
                message_id="bridge:1" if duplicate else "bridge:3",
            )

        server, port = await run_server(handler)
        async with server:
            with pytest.raises(GameBridgeSequenceError):
                await GameBridgeClient(configuration(port)).connect()

    asyncio.run(ordering(duplicate=True))
    asyncio.run(ordering(duplicate=False))


def test_oversized_frame_is_rejected_before_body_read() -> None:
    async def scenario() -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await read_frame(reader)
            writer.write(struct.pack(">I", 2_000_000))
            await writer.drain()

        server, port = await run_server(handler)
        async with server:
            with pytest.raises(GameBridgeMessageSizeError):
                await GameBridgeClient(configuration(port)).connect()

    asyncio.run(scenario())


def test_changed_game_identity_requires_explicit_resynchronization() -> None:
    async def stale_scenario() -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            await send_fixture(writer, "bridge_hello.json", correlation_id=hello.message_id)
            await send_fixture(writer, "capability_manifest.json", game_session_id="new-session")

        server, port = await run_server(handler)
        async with server:
            with pytest.raises(GameBridgeSequenceError, match="game session"):
                await GameBridgeClient(configuration(port)).connect()

    asyncio.run(stale_scenario())

    async def resync_scenario() -> GameBridgeClient:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            hello = await read_frame(reader)
            await send_fixture(writer, "bridge_hello.json", correlation_id=hello.message_id)
            await send_fixture(writer, "capability_manifest.json")
            request = await read_frame(reader)
            assert request.message_type is MessageType.RESYNCHRONIZATION_REQUEST
            await send_fixture(
                writer,
                "bridge_hello.json",
                correlation_id=request.message_id,
                sequence=10,
                message_id="bridge:10",
                game_session_id="new-session",
            )
            await send_fixture(
                writer,
                "capability_manifest.json",
                sequence=11,
                message_id="bridge:11",
                game_session_id="new-session",
            )

        server, port = await run_server(handler)
        async with server:
            client = GameBridgeClient(configuration(port))
            await client.connect()
            await client.resynchronize(reason="identity_changed")
            await client.close()
            return client

    assert asyncio.run(resync_scenario()).game_session_id == "new-session"
