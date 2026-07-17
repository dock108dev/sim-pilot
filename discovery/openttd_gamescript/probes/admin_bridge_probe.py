"""Probe OpenTTD 15.3's official bidirectional Admin/GameScript packets.

This is deliberately outside the production package. It only connects to loopback.
Company mutation additionally requires SIM_PILOT_OPENTTD_GS_DISCOVERY_WRITES=1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import struct
import time
import uuid
from typing import Any

from discovery.openttd_gamescript import BridgeEnvelope
from sim_pilot.openttd.config import openttd_configuration
from sim_pilot.openttd.protocol import PacketType, encode_join

ADMIN_GAMESCRIPT = 6
SERVER_GAMESCRIPT = 124
ADMIN_UPDATE_GAMESCRIPT = 9
ADMIN_FREQUENCY_AUTOMATIC = 1 << 6


def _encode_raw(packet_type: int, payload: bytes = b"") -> bytes:
    body = bytes([packet_type]) + payload
    return struct.pack("<H", len(body) + 2) + body


def _cstring(value: str) -> bytes:
    if "\x00" in value:
        raise ValueError("Admin JSON cannot contain NUL")
    return value.encode("utf-8") + b"\x00"


async def _read_packet(reader: asyncio.StreamReader, timeout: float) -> tuple[int, bytes]:
    header = await asyncio.wait_for(reader.readexactly(2), timeout)
    size = struct.unpack("<H", header)[0]
    body = await asyncio.wait_for(reader.readexactly(size - 2), timeout)
    return body[0], body[1:]


def _decode_gamescript(payload: bytes) -> BridgeEnvelope:
    if not payload.endswith(b"\x00"):
        raise ValueError("GameScript packet did not contain a terminated JSON string")
    return BridgeEnvelope.from_json(payload[:-1].decode("utf-8"))


async def probe(
    *, company_id: int, mutate: bool, samples: int, wait_for_heartbeat: bool
) -> dict[str, Any]:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD_GS") != "1":
        raise RuntimeError("set SIM_PILOT_LIVE_OPENTTD_GS=1 for a live probe")
    if mutate and os.getenv("SIM_PILOT_OPENTTD_GS_DISCOVERY_WRITES") != "1":
        raise RuntimeError("write probe requires SIM_PILOT_OPENTTD_GS_DISCOVERY_WRITES=1")
    config = openttd_configuration()
    if config.host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("discovery probes require a literal loopback host")

    reader, writer = await asyncio.open_connection(config.host, config.port)
    writer.write(encode_join(config.password.get_secret_value(), "sim-pilot-gs-probe"))
    await writer.drain()
    seen_welcome = False
    while not seen_welcome:
        packet_type, _ = await _read_packet(reader, config.connection_timeout_seconds)
        seen_welcome = packet_type == PacketType.SERVER_WELCOME
    writer.write(
        _encode_raw(
            PacketType.ADMIN_UPDATE_FREQUENCY,
            struct.pack("<HH", ADMIN_UPDATE_GAMESCRIPT, ADMIN_FREQUENCY_AUTOMATIC),
        )
    )
    await writer.drain()

    run_id = uuid.uuid4().hex
    instance_id = f"python-probe-{run_id}"
    latencies: list[float] = []
    responses: list[BridgeEnvelope] = []

    async def request(message_id: str, message_type: str, payload: dict[str, object]) -> None:
        command = {
            "protocol_version": 1,
            "message_id": message_id,
            "message_type": message_type,
            "script_instance_id": instance_id,
            "company_id": company_id,
            "payload": payload,
        }
        started = time.perf_counter()
        writer.write(_encode_raw(ADMIN_GAMESCRIPT, _cstring(json.dumps(command))))
        await writer.drain()
        while True:
            packet_type, packet_payload = await _read_packet(
                reader, config.observation_timeout_seconds
            )
            if packet_type != SERVER_GAMESCRIPT:
                continue
            response = _decode_gamescript(packet_payload)
            responses.append(response)
            if response.correlation_id == message_id:
                latencies.append((time.perf_counter() - started) * 1000)
                return

    def command_id(value: str) -> str:
        return f"{run_id}:{value}"

    await request(command_id("hello-1"), "hello_request", {})
    for index in range(samples):
        await request(command_id(f"ping-{index}"), "ping", {})
    await request(command_id("unsupported-1"), "unsupported", {})
    duplicate_id = command_id("duplicate-1")
    await request(duplicate_id, "ping", {})
    await request(duplicate_id, "ping", {})
    if mutate:
        await request(
            command_id("company-probe-1"),
            "probe_company",
            {"temporary_name": f"Sim Pilot Probe {uuid.uuid4().hex[:8]}"},
        )
    heartbeat_seen = False
    if wait_for_heartbeat:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            packet_type, packet_payload = await _read_packet(reader, deadline - time.monotonic())
            if packet_type != SERVER_GAMESCRIPT:
                continue
            response = _decode_gamescript(packet_payload)
            responses.append(response)
            if response.message_type.value == "heartbeat":
                heartbeat_seen = True
                break
    writer.write(_encode_raw(PacketType.ADMIN_QUIT))
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    return {
        "server": f"{config.host}:{config.port}",
        "company_id": company_id,
        "write_opt_in": mutate,
        "heartbeat_seen": heartbeat_seen,
        "latency_ms": {
            "minimum": min(latencies),
            "median": statistics.median(latencies),
            "maximum": max(latencies),
            "samples": len(latencies),
        },
        "responses": [response.model_dump(mode="json") for response in responses],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--wait-for-heartbeat", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        probe(
            company_id=args.company_id,
            mutate=args.write,
            samples=args.samples,
            wait_for_heartbeat=args.wait_for_heartbeat,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
