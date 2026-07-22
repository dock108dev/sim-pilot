import asyncio
import json
from pathlib import Path

import pytest

from sim_pilot.game_bridge import CapabilityManifestPayload
from sim_pilot.game_bridge.models import FullSnapshotResponsePayload, GameSnapshot, parse_envelope
from sim_pilot.rail_route.bridge.proof import prove_read_only_bridge


class _FakeClient:
    def __init__(self, snapshot: GameSnapshot) -> None:
        self.snapshot = snapshot

    async def connect(self) -> CapabilityManifestPayload:
        return CapabilityManifestPayload(
            observation_surfaces=("game_state", "trains"), gameplay_actions=()
        )

    async def request_full_snapshot(self) -> GameSnapshot:
        return self.snapshot

    async def close(self) -> None:
        return None


def _snapshot() -> GameSnapshot:
    value = json.loads(
        Path("tests/fixtures/game_bridge/v2/full_snapshot_response.json").read_text()
    )
    value["protocol_version"] = 3
    value["adapter_version"] = "rail-route-ui-observer-v1"
    value["payload"]["snapshot"]["adapter_version"] = "rail-route-ui-observer-v1"
    envelope = parse_envelope(json.dumps(value).encode())
    assert isinstance(envelope.payload, FullSnapshotResponsePayload)
    return envelope.payload.snapshot


def test_read_only_proof_hashes_semantics_and_save_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot()
    user_data = tmp_path / "RailRoute"
    saves = user_data / "saves"
    saves.mkdir(parents=True)
    (saves / "yard.save").write_bytes(b"unchanged")
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.proof.rail_route_bridge_client",
        lambda: _FakeClient(snapshot),
    )

    proof = asyncio.run(prove_read_only_bridge(user_data=user_data))

    assert proof.passed
    assert proof.paused
    assert proof.save_file_count == 1
    assert proof.save_fingerprint_before == proof.save_fingerprint_after
    assert proof.semantic_fingerprint_before == proof.semantic_fingerprint_after
