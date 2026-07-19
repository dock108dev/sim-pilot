from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sim_pilot.domain.world import (
    CapabilityCoverage,
    Company,
    Coordinates,
    CoverageStatus,
    Town,
    WorldSnapshot,
    WorldSnapshotMetadata,
)


def snapshot() -> WorldSnapshot:
    return WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id="snapshot-1",
            world_id="world-1",
            game="openttd",
            game_version="15.3",
            game_date=10,
            capture_started_game_date=10,
            capture_completed_game_date=10,
            complete=True,
            capability_fingerprint="fingerprint",
            save_generation=2,
            bridge_sequence=4,
            captured_at=datetime.now(UTC),
        ),
        coverage=(CapabilityCoverage(category="towns", status=CoverageStatus.AVAILABLE),),
        companies=(Company(id="company-1", name="Company", cash=10, loan=0),),
        towns=(
            Town(
                id="town-1",
                name="Town",
                population=100,
                coordinates=Coordinates(x=1, y=2),
            ),
        ),
    )


def test_world_snapshot_is_strict_immutable_and_round_trips() -> None:
    value = snapshot()
    assert WorldSnapshot.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate({**value.model_dump(), "unknown": True}, strict=True)


def test_unavailable_values_are_not_fabricated() -> None:
    town = snapshot().towns[0]
    assert town.authority_rating is None
    assert town.station_count is None
