from datetime import UTC, datetime, timedelta
from pathlib import Path

from sim_pilot.analysis.freshness import SnapshotCache, SnapshotIdentity
from tests.analysis.helpers import snapshot

NOW = datetime(2026, 7, 20, tzinfo=UTC)


def test_snapshot_cache_requires_verified_matching_identity(tmp_path: Path) -> None:
    world = snapshot()
    cache = SnapshotCache(tmp_path / "cache.json", clock=lambda: NOW)
    cache.store(world)

    assert cache.load(None) is None
    loaded = cache.load(SnapshotIdentity.from_snapshot(world))
    assert loaded == (world, 0.0)


def test_snapshot_cache_rejects_identity_changes_and_expiration(tmp_path: Path) -> None:
    world = snapshot()
    now = NOW
    cache = SnapshotCache(tmp_path / "cache.json", clock=lambda: now)
    cache.store(world)
    identity = SnapshotIdentity.from_snapshot(world)
    changed = SnapshotIdentity(
        world_id=identity.world_id,
        save_generation=identity.save_generation + 1,
        capability_fingerprint=identity.capability_fingerprint,
    )
    assert cache.load(changed) is None

    now += timedelta(seconds=31)
    assert cache.load(SnapshotIdentity.from_snapshot(world)) is None


def test_snapshot_cache_does_not_store_partial_snapshot(tmp_path: Path) -> None:
    world = snapshot().model_copy(
        update={"metadata": snapshot().metadata.model_copy(update={"complete": False})}
    )
    path = tmp_path / "cache.json"
    SnapshotCache(path).store(world)
    assert not path.exists()
