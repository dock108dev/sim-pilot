import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sim_pilot.analysis.contracts import SnapshotSource
from sim_pilot.analysis.freshness import SnapshotIdentity, SnapshotVerification
from sim_pilot.cli import (
    AnalysisSnapshotAcquisition,
    _analysis_snapshot,  # pyright: ignore[reportPrivateUsage]
)
from sim_pilot.domain.world import WorldSnapshot
from tests.analysis.helpers import snapshot


def _verification(world: WorldSnapshot, **identity_changes: object) -> SnapshotVerification:
    identity = SnapshotIdentity.from_snapshot(world, bridge_company_context=0).model_copy(
        update=identity_changes
    )
    return SnapshotVerification(
        identity=identity,
        verified_at=datetime.now(UTC),
        bridge_sequence=world.metadata.bridge_sequence,
        synchronization_state="identity_verified",
        openttd_version="15.3",
        bridge_protocol_version=2,
        script_version=2,
    )


def test_repeated_acquisition_reuses_only_live_verified_compatible_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = snapshot()
    synchronized = _verification(world).model_copy(update={"synchronization_state": "synchronized"})
    calls = {"collect": 0, "probe": 0}

    async def collect() -> AnalysisSnapshotAcquisition:
        calls["collect"] += 1
        return AnalysisSnapshotAcquisition(
            snapshot=world,
            source=SnapshotSource.FRESH_COLLECTION,
            maximum_acceptable_age_seconds=0,
            collection_duration_seconds=7.6,
            verification=synchronized,
        )

    async def probe() -> SnapshotVerification:
        calls["probe"] += 1
        return _verification(world)

    monkeypatch.setattr("sim_pilot.cli.analysis_session_directory", lambda: tmp_path)
    monkeypatch.setattr("sim_pilot.cli._collect_analysis_snapshot", collect)
    monkeypatch.setattr("sim_pilot.cli._probe_openttd_snapshot_identity", probe)

    first = asyncio.run(_analysis_snapshot(None, False))
    repeated = asyncio.run(_analysis_snapshot(None, False))

    assert first.source is SnapshotSource.FRESH_COLLECTION
    assert repeated.source is SnapshotSource.COMPATIBLE_CACHE
    assert repeated.snapshot == world
    assert calls == {"collect": 1, "probe": 1}
    assert repeated.metadata().maximum_acceptable_age_seconds == 5


def test_bridge_resynchronization_or_company_change_forces_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_world = snapshot()
    changed_world = snapshot(
        identifier="snapshot-after-resync",
        world_id="world-after-resync",
        observer_company_id="company-after-resync",
    )
    collections = iter((first_world, changed_world))
    count = 0

    async def collect() -> AnalysisSnapshotAcquisition:
        nonlocal count
        count += 1
        world = next(collections)
        return AnalysisSnapshotAcquisition(
            snapshot=world,
            source=SnapshotSource.FRESH_COLLECTION,
            maximum_acceptable_age_seconds=5,
            collection_duration_seconds=1,
            verification=_verification(world).model_copy(
                update={"synchronization_state": "synchronized"}
            ),
        )

    async def changed_probe() -> SnapshotVerification:
        return _verification(changed_world)

    monkeypatch.setattr("sim_pilot.cli.analysis_session_directory", lambda: tmp_path)
    monkeypatch.setattr("sim_pilot.cli._collect_analysis_snapshot", collect)
    monkeypatch.setattr("sim_pilot.cli._probe_openttd_snapshot_identity", changed_probe)

    asyncio.run(_analysis_snapshot(None, False))
    result = asyncio.run(_analysis_snapshot(None, False))

    assert count == 2
    assert result.source is SnapshotSource.FRESH_COLLECTION
    assert result.snapshot.metadata.world_id == "world-after-resync"


def test_fresh_and_zero_maximum_age_bypass_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = snapshot()
    calls = 0

    async def collect() -> AnalysisSnapshotAcquisition:
        nonlocal calls
        calls += 1
        return AnalysisSnapshotAcquisition(
            snapshot=world,
            source=SnapshotSource.FRESH_COLLECTION,
            maximum_acceptable_age_seconds=0,
            collection_duration_seconds=1,
            verification=_verification(world).model_copy(
                update={"synchronization_state": "synchronized"}
            ),
        )

    monkeypatch.setattr("sim_pilot.cli.analysis_session_directory", lambda: tmp_path)
    monkeypatch.setattr("sim_pilot.cli._collect_analysis_snapshot", collect)

    asyncio.run(_analysis_snapshot(None, False))
    asyncio.run(_analysis_snapshot(None, False, True))
    asyncio.run(_analysis_snapshot(None, False, False, 0))

    assert calls == 3


def test_selected_snapshot_maximum_age_fails_closed(tmp_path: Path) -> None:
    world = snapshot().model_copy(
        update={
            "metadata": snapshot().metadata.model_copy(
                update={"captured_at": datetime(2020, 1, 1, tzinfo=UTC)}
            )
        }
    )
    path = tmp_path / "old.json"
    path.write_text(world.model_dump_json(), encoding="utf-8")

    try:
        asyncio.run(_analysis_snapshot(path, False, False, 5))
    except ValueError as error:
        assert "exceeds" in str(error)
    else:
        raise AssertionError("an expired selected snapshot must fail closed")
