"""Live read-only proof over paused semantic state and actual Rail Route save bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sim_pilot.game_bridge import GameSnapshot

from .client import rail_route_bridge_client
from .models import BridgeReadOnlyProof

DEFAULT_USER_DATA = Path.home() / "Library/Application Support/RailRoute"


async def prove_read_only_bridge(*, user_data: Path = DEFAULT_USER_DATA) -> BridgeReadOnlyProof:
    save_before, save_count = _save_fingerprint(user_data)
    first_client = rail_route_bridge_client()
    try:
        capabilities = await first_client.connect()
        first = await first_client.request_full_snapshot()
    finally:
        await first_client.close()

    second_client = rail_route_bridge_client()
    try:
        second_capabilities = await second_client.connect()
        second = await second_client.request_full_snapshot()
    finally:
        await second_client.close()
    save_after, after_count = _save_fingerprint(user_data)

    before_semantic = _semantic_fingerprint(first)
    after_semantic = _semantic_fingerprint(second)
    reasons: list[str] = []
    paused = first.game_state.get("paused") is True and second.game_state.get("paused") is True
    if not paused:
        reasons.append("game must remain paused for a deterministic non-mutation proof")
    if capabilities.gameplay_actions != ("set_route",) or second_capabilities.gameplay_actions != (
        "set_route",
    ):
        reasons.append("bridge action catalog was not exactly set_route")
    if first.bridge_instance_id != second.bridge_instance_id:
        reasons.append("bridge instance changed between observations")
    if first.game_session_id != second.game_session_id:
        reasons.append("game session changed between observations")
    if before_semantic != after_semantic:
        reasons.append("paused semantic state changed between read-only observations")
    if save_count != after_count or save_before != save_after:
        reasons.append("Rail Route save or community-level bytes changed")

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
        save_file_count=save_count,
        save_fingerprint_before=save_before,
        save_fingerprint_after=save_after,
        reasons=tuple(reasons),
    )


def _semantic_fingerprint(snapshot: GameSnapshot) -> str:
    value = {
        "map_identity": snapshot.map_identity.model_dump(mode="json"),
        "save_identity": snapshot.save_identity.model_dump(mode="json"),
        "game_state": snapshot.game_state,
        "surfaces": [surface.model_dump(mode="json") for surface in snapshot.surfaces],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _save_fingerprint(user_data: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(
        (
            path
            for directory in (user_data / "saves", user_data / "community levels")
            if directory.is_dir()
            for path in directory.rglob("*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.relative_to(user_data).as_posix(),
    )
    for path in files:
        relative = path.relative_to(user_data).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), len(files)
