import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sim_pilot.analysis.freshness import (
    SnapshotCache,
    SnapshotCacheStatus,
    SnapshotIdentity,
)
from sim_pilot.domain.world import WorldSnapshot
from tests.analysis.helpers import snapshot

NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _world() -> WorldSnapshot:
    world = snapshot()
    return world.model_copy(
        update={"metadata": world.metadata.model_copy(update={"captured_at": NOW})}
    )


def _identity(world: WorldSnapshot | None = None, *, company_context: int = 0) -> SnapshotIdentity:
    return SnapshotIdentity.from_snapshot(world or _world(), bridge_company_context=company_context)


def _store(cache: SnapshotCache, world: WorldSnapshot | None = None) -> None:
    value = world or _world()
    cache.store(
        value,
        identity=_identity(value),
        collection_duration_seconds=7.5,
    )


def test_snapshot_cache_requires_verified_matching_identity(tmp_path: Path) -> None:
    world = _world()
    cache = SnapshotCache(tmp_path / "cache.json", clock=lambda: NOW)
    _store(cache, world)

    assert cache.load(None, maximum_age_seconds=5).status is SnapshotCacheStatus.INCOMPATIBLE
    loaded = cache.load(_identity(world), maximum_age_seconds=5)
    assert loaded.status is SnapshotCacheStatus.HIT
    assert loaded.snapshot == world
    assert loaded.age_seconds == 0


def test_snapshot_cache_expires_without_exposing_data(tmp_path: Path) -> None:
    now = NOW
    cache = SnapshotCache(tmp_path / "cache.json", clock=lambda: now)
    _store(cache)
    now += timedelta(seconds=6)

    result = cache.load(_identity(), maximum_age_seconds=5)
    assert result.status is SnapshotCacheStatus.EXPIRED
    assert result.snapshot is None


def test_snapshot_cache_rejects_world_company_generation_capability_and_context_changes(
    tmp_path: Path,
) -> None:
    world = _world()
    cache = SnapshotCache(tmp_path / "cache.json", clock=lambda: NOW)
    _store(cache, world)
    identity = _identity(world)
    changes = (
        {"world_id": "different-world"},
        {"observer_company_id": "company:different"},
        {"save_generation": identity.save_generation + 1},
        {"capability_fingerprint": "different-capabilities"},
        {"bridge_company_context": 1},
    )

    for change in changes:
        result = cache.load(identity.model_copy(update=change), maximum_age_seconds=5)
        assert result.status is SnapshotCacheStatus.INCOMPATIBLE
        assert result.snapshot is None


def test_snapshot_cache_does_not_store_partial_snapshot(tmp_path: Path) -> None:
    world = _world()
    world = world.model_copy(
        update={"metadata": world.metadata.model_copy(update={"complete": False})}
    )
    path = tmp_path / "cache.json"
    SnapshotCache(path).store(
        world,
        identity=_identity(world),
        collection_duration_seconds=1,
    )
    assert not path.exists()


def test_snapshot_cache_fails_closed_on_corruption_and_identity_tampering(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = SnapshotCache(path, clock=lambda: NOW)
    path.write_text("not-json", encoding="utf-8")
    assert cache.candidate_status(5).status is SnapshotCacheStatus.CORRUPT

    _store(cache)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["identity"]["world_id"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = cache.load(_identity(), maximum_age_seconds=5)
    assert result.status is SnapshotCacheStatus.CORRUPT
    assert result.snapshot is None


def test_snapshot_cache_serializes_concurrent_refreshes(tmp_path: Path) -> None:
    cache = SnapshotCache(tmp_path / "cache.json")
    active = 0
    peak = 0
    guard = threading.Lock()

    def enter() -> None:
        nonlocal active, peak
        with cache.exclusive():
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1

    threads = [threading.Thread(target=enter) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1
