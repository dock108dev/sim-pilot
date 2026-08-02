from datetime import UTC, datetime

import pytest

from sim_pilot.game_bridge import (
    Architecture,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.software_inc.bridge.query import entity_from, render_entity, surface_from
from sim_pilot.software_inc.errors import SoftwareIncCompatibilityError


def _snapshot() -> GameSnapshot:
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=1,
        bridge_instance_id="bridge-test",
        game_session_id="session-test",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not exposed"),
        save_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="disposable"),
        game_state={"force_pause": True, "simulation_speed": "0"},
        surfaces=(
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="education",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=("duration_months",),
                ),
                entities=(),
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="employees",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=("name", "role"),
                ),
                entities=(
                    ObservedEntity(
                        entity_type="employee",
                        entity_id="42",
                        values={"name": "Jane Doe", "role": "Programmer"},
                    ),
                ),
            ),
        ),
    )


def test_query_accepts_singular_and_hyphenated_surface_aliases() -> None:
    snapshot = _snapshot()

    assert surface_from(snapshot, "employee").coverage.surface == "employees"
    assert surface_from(snapshot, "course").coverage.surface == "education"
    assert entity_from(snapshot, "employee", "Jane Doe").entity_id == "42"
    assert '"role": "Programmer"' in render_entity(entity_from(snapshot, "employees", "42"))


def test_query_rejects_unknown_and_missing_entities() -> None:
    with pytest.raises(SoftwareIncCompatibilityError, match="unknown Software Inc. surface"):
        surface_from(_snapshot(), "contracts")
    with pytest.raises(SoftwareIncCompatibilityError, match="no employees entity"):
        entity_from(_snapshot(), "employee", "missing")
