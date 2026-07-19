"""OpenTTD Admin Network client tests with a deterministic TCP server."""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import cast

import pytest
from pydantic import SecretStr

from sim_pilot.openttd.client import OpenTTDAdminClient
from sim_pilot.openttd.config import OpenTTDConfiguration
from sim_pilot.openttd.errors import (
    OpenTTDDisconnectedError,
    OpenTTDProtocolMismatchError,
    OpenTTDStateUnavailableError,
    OpenTTDUnsupportedVersionError,
)
from sim_pilot.openttd.protocol import PacketType, encode_packet

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


def _text(value: str) -> bytes:
    return value.encode() + b"\x00"


def _protocol(version: int = 3, update_types: tuple[int, ...] = (0, 2, 3, 4)) -> bytes:
    payload = bytes([version])
    for update_type in update_types:
        frequency = 64 if update_type == 9 else 1
        payload += bytes([1]) + struct.pack("<HH", update_type, frequency)
    payload += bytes([0])
    return encode_packet(PacketType.SERVER_PROTOCOL, payload)


def _welcome(version: str = "15.3") -> bytes:
    payload = b"".join(
        (
            _text("Test Server"),
            _text(version),
            bytes([1]),
            _text(""),
            struct.pack("<IBIHH", 12345, 0, 712223, 256, 256),
        )
    )
    return encode_packet(PacketType.SERVER_WELCOME, payload)


def _company_info() -> bytes:
    payload = b"".join(
        (
            bytes([0]),
            _text("Test Transport"),
            _text("Ada Lovelace"),
            bytes([1, 1]),
            struct.pack("<I", 1950),
            bytes([0, 0]),
        )
    )
    return encode_packet(PacketType.SERVER_COMPANY_INFO, payload)


def _economy() -> bytes:
    payload = b"".join(
        (
            bytes([0]),
            struct.pack("<qQqH", 425000, 50000, 175000, 120),
            struct.pack("<qHH", 850000, 650, 450),
            struct.pack("<qHH", 700000, 610, 420),
        )
    )
    return encode_packet(PacketType.SERVER_COMPANY_ECONOMY, payload)


def _stats() -> bytes:
    return encode_packet(
        PacketType.SERVER_COMPANY_STATS,
        bytes([0]) + struct.pack("<10H", 8, 5, 3, 2, 1, 6, 4, 3, 2, 1),
    )


async def _read_request(reader: asyncio.StreamReader) -> bytes:
    size = struct.unpack("<H", await reader.readexactly(2))[0]
    return await reader.readexactly(size - 2)


async def _success_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await _read_request(reader)
        writer.write(_protocol() + _welcome())
        await writer.drain()
        responses = (
            _company_info(),
            encode_packet(PacketType.SERVER_DATE, struct.pack("<I", 712588)),
            _economy(),
            _stats(),
        )
        for response in responses:
            await _read_request(reader)
            writer.write(response)
            await writer.drain()
        with suppress(asyncio.IncompleteReadError):
            await _read_request(reader)
    finally:
        writer.close()
        await writer.wait_closed()


async def _run_client(handler: Handler) -> tuple[OpenTTDAdminClient, asyncio.Server]:
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = OpenTTDAdminClient(
        OpenTTDConfiguration(
            port=port,
            password=SecretStr("secret"),
            connection_timeout_seconds=0.5,
            observation_timeout_seconds=0.1,
        )
    )
    return client, server


def test_client_connects_authenticates_and_collects_selected_company() -> None:
    async def scenario() -> None:
        client, server = await _run_client(_success_server)
        async with server:
            await client.connect()
            state = await client.collect_state()
            assert client.metadata.protocol_version == 3
            assert state.game_date == "1951-01-01"
            assert state.company.cash == 425000
            assert state.company.vehicles.total == 19
            await client.close()

    asyncio.run(scenario())


def test_close_keeps_cleanup_resilient_but_reports_transport_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class InjectableClient(OpenTTDAdminClient):
        def inject_writer(self, writer: asyncio.StreamWriter) -> None:
            self._writer = writer

        @property
        def has_writer(self) -> bool:
            return self._writer is not None

    class FailingWriter:
        def write(self, data: bytes) -> None:
            del data
            raise ConnectionError("peer reset")

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            raise OSError("close failed")

    client = InjectableClient(OpenTTDConfiguration(password=SecretStr("secret")))
    client.inject_writer(cast("asyncio.StreamWriter", FailingWriter()))

    with caplog.at_level(logging.WARNING, logger="sim_pilot.openttd.client"):
        asyncio.run(client.close())

    assert client.has_writer is False
    assert "stage=admin_quit error_type=ConnectionError" in caplog.text
    assert "stage=wait_closed error_type=OSError" in caplog.text


def test_client_executes_bounded_rcon_and_matches_completion_command() -> None:
    command = 'server_name "Sim Pilot"'

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_protocol() + _welcome())
        await writer.drain()
        request = await _read_request(reader)
        assert request == bytes([PacketType.ADMIN_RCON]) + _text(command)
        writer.write(
            encode_packet(PacketType.SERVER_RCON, struct.pack("<H", 1) + _text("changed"))
            + encode_packet(PacketType.SERVER_RCON_END, _text(command))
        )
        await writer.drain()
        with suppress(asyncio.IncompleteReadError):
            await _read_request(reader)
        writer.close()
        await writer.wait_closed()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            await client.connect()
            assert await client.execute_rcon(command) == ("changed",)
            await client.close()

    asyncio.run(scenario())


def test_client_routes_gamescript_json_on_the_single_admin_stream() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_protocol(update_types=(0, 2, 3, 4, 9)) + _welcome())
        await writer.drain()
        subscription = await _read_request(reader)
        assert subscription == bytes([PacketType.ADMIN_UPDATE_FREQUENCY]) + struct.pack(
            "<HH", 9, 64
        )
        request = await _read_request(reader)
        assert request == bytes([PacketType.ADMIN_GAMESCRIPT]) + _text('{"ping":true}')
        writer.write(encode_packet(PacketType.SERVER_GAMESCRIPT, _text('{"pong":true}')))
        await writer.drain()
        with suppress(asyncio.IncompleteReadError):
            await _read_request(reader)
        writer.close()
        await writer.wait_closed()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            await client.connect()
            await client.subscribe_gamescript()
            await client.send_gamescript('{"ping":true}')
            assert await client.receive_gamescript() == '{"pong":true}'
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("protocol", "version", "error_type"),
    [
        (2, "15.3", OpenTTDProtocolMismatchError),
        (3, "16.0-beta1", OpenTTDUnsupportedVersionError),
    ],
)
def test_client_rejects_unsupported_protocol_or_version(
    protocol: int, version: str, error_type: type[Exception]
) -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_protocol(protocol) + _welcome(version))
        await writer.drain()
        with suppress(ConnectionError):
            writer.close()
            await writer.wait_closed()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            with pytest.raises(error_type):
                await client.connect()

    asyncio.run(scenario())


def test_client_translates_missing_company_to_state_unavailable() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_protocol() + _welcome())
        await writer.drain()
        await _read_request(reader)
        await asyncio.sleep(0.2)
        writer.close()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            await client.connect()
            with pytest.raises(OpenTTDStateUnavailableError, match="company 0"):
                await client.collect_state()
            await client.close()

    asyncio.run(scenario())


def test_client_rejects_protocol_without_required_poll_capability() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.write(_protocol(update_types=(0, 2, 3)) + _welcome())
        await writer.drain()
        with suppress(ConnectionError):
            writer.close()
            await writer.wait_closed()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            with pytest.raises(OpenTTDProtocolMismatchError, match="COMPANY_STATS"):
                await client.connect()

    asyncio.run(scenario())


def test_client_translates_disconnect_during_authentication() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _read_request(reader)
        writer.close()
        await writer.wait_closed()

    async def scenario() -> None:
        client, server = await _run_client(handler)
        async with server:
            with pytest.raises(OpenTTDDisconnectedError):
                await client.connect()

    asyncio.run(scenario())
