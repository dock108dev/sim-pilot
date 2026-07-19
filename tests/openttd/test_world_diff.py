from datetime import UTC, datetime

from sim_pilot.domain.world import (
    CapabilityCoverage,
    Coordinates,
    CoverageStatus,
    Town,
    WorldSnapshot,
    WorldSnapshotMetadata,
)
from sim_pilot.openttd.world_diff import diff_world


def snapshot(
    population: int, *, complete: bool = True, include_second: bool = False
) -> WorldSnapshot:
    towns = [
        Town(id="town:1", name="One", population=population, coordinates=Coordinates(x=1, y=1))
    ]
    if include_second:
        towns.append(
            Town(id="town:2", name="Two", population=20, coordinates=Coordinates(x=2, y=2))
        )
    return WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id=f"snapshot:{population}:{include_second}",
            world_id="world:1",
            game="openttd",
            game_version="15.3",
            game_date=1,
            capture_started_game_date=1,
            capture_completed_game_date=1,
            complete=complete,
            capability_fingerprint="fingerprint",
            save_generation=1,
            bridge_sequence=1,
            captured_at=datetime.now(UTC),
        ),
        coverage=(CapabilityCoverage(category="towns", status=CoverageStatus.AVAILABLE),),
        towns=tuple(towns),
    )


def test_diff_is_typed_deterministic_and_tracks_population_and_addition() -> None:
    result = diff_world(snapshot(10), snapshot(11, include_second=True))
    assert [change.change_type for change in result.changes] == [
        "entity_added",
        "field_changed",
    ]
    assert result.changes_from_snapshot_id == "snapshot:10:False"


def test_incomplete_snapshot_does_not_report_false_removal() -> None:
    result = diff_world(snapshot(10, include_second=True), snapshot(10, complete=False))
    assert all(change.change_type != "entity_removed" for change in result.changes)


def test_different_worlds_fail_closed() -> None:
    current = snapshot(10)
    other = current.model_copy(
        update={"metadata": current.metadata.model_copy(update={"world_id": "world:2"})}
    )
    try:
        diff_world(current, other)
    except ValueError as error:
        assert "different worlds" in str(error)
    else:
        raise AssertionError("different world identities must not be diffed")
