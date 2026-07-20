import asyncio
import os
from pathlib import Path
from time import perf_counter

import pytest

from sim_pilot.analysis.contracts import SnapshotSource
from sim_pilot.cli import _analysis_snapshot  # pyright: ignore[reportPrivateUsage]


@pytest.mark.live
def test_compatible_five_second_snapshot_returns_under_two_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD_LATENCY") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD_LATENCY=1 for Phase 9.2 live latency")
    assert os.getenv("SIM_PILOT_OPENTTD_ALLOW_WRITES", "0") == "0"
    assert os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES", "0") == "0"
    monkeypatch.setattr("sim_pilot.cli.analysis_session_directory", lambda: tmp_path)

    fresh = asyncio.run(_analysis_snapshot(None, False, True))
    started = perf_counter()
    repeated = asyncio.run(_analysis_snapshot(None, False, False, 5))
    elapsed = perf_counter() - started

    assert fresh.source is SnapshotSource.FRESH_COLLECTION
    assert repeated.source is SnapshotSource.COMPATIBLE_CACHE
    assert repeated.snapshot.metadata.world_id == fresh.snapshot.metadata.world_id
    assert repeated.snapshot.metadata.observer_company_id == (
        fresh.snapshot.metadata.observer_company_id
    )
    assert repeated.metadata().snapshot_age_seconds <= 5
    assert elapsed < 2
