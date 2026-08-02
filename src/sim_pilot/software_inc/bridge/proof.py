"""Reconnect and save-byte non-mutation proof for the Software Inc. bridge."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery

from .client import software_inc_bridge_client
from .models import BridgeReadOnlyProof


async def prove_read_only_bridge(
    *, save_paths: tuple[Path, ...] | None = None
) -> BridgeReadOnlyProof:
    paths = save_paths or SoftwareIncDiscovery().inspect().save_path_candidates
    save_before, count_before = _save_fingerprint(paths)
    first_client = software_inc_bridge_client()
    try:
        capabilities = await first_client.connect()
        first = await first_client.request_full_snapshot()
    finally:
        await first_client.close()
    second_client = software_inc_bridge_client()
    try:
        second_capabilities = await second_client.connect()
        second = await second_client.request_full_snapshot()
    finally:
        await second_client.close()
    save_after, count_after = _save_fingerprint(paths)
    before_semantic = _semantic_fingerprint(first)
    after_semantic = _semantic_fingerprint(second)
    speed = first.game_state.get("simulation_speed")
    paused = first.game_state.get("force_pause") is True or speed in {"0", "0.0"}
    reasons: list[str] = []
    if not paused:
        reasons.append("pause Software Inc. before running the deterministic proof")
    if capabilities.gameplay_actions or second_capabilities.gameplay_actions:
        reasons.append("gameplay action catalog is not empty")
    if (
        first.bridge_instance_id != second.bridge_instance_id
        or first.game_session_id != second.game_session_id
    ):
        reasons.append("bridge or game session identity changed")
    if before_semantic != after_semantic:
        reasons.append("paused semantic state changed across reconnect")
    if count_before != count_after or save_before != save_after:
        reasons.append("Software Inc. save bytes changed")
    observed = tuple(
        surface.coverage.surface
        for surface in first.surfaces
        if surface.coverage.status.value.startswith("observed_")
    )
    return BridgeReadOnlyProof(
        passed=not reasons,
        bridge_instance_id=first.bridge_instance_id,
        game_session_id=first.game_session_id,
        paused=paused,
        gameplay_actions=capabilities.gameplay_actions,
        observed_surfaces=observed,
        semantic_fingerprint_before=before_semantic,
        semantic_fingerprint_after=after_semantic,
        save_file_count=count_before,
        save_fingerprint_before=save_before,
        save_fingerprint_after=save_after,
        completed_at=datetime.now(UTC),
        reasons=tuple(reasons),
    )


def _semantic_fingerprint(snapshot: GameSnapshot) -> str:
    value = {
        "map_identity": snapshot.map_identity.model_dump(mode="json"),
        "save_identity": snapshot.save_identity.model_dump(mode="json"),
        "game_state": snapshot.game_state,
        "surfaces": [item.model_dump(mode="json") for item in snapshot.surfaces],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _save_fingerprint(paths: tuple[Path, ...]) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(
        {
            path.resolve()
            for root in paths
            if root.is_dir()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        },
        key=str,
    )
    for path in files:
        encoded = str(path).encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), len(files)


def save_fingerprint(paths: tuple[Path, ...] | None = None) -> tuple[str, int]:
    """Return the deterministic fingerprint used by read-only and UI acceptance proofs."""
    selected = paths or SoftwareIncDiscovery().inspect().save_path_candidates
    return _save_fingerprint(selected)
