from datetime import UTC, datetime

from sim_pilot.domain.world import (
    CapabilityCoverage,
    Company,
    CoverageStatus,
    Vehicle,
    WorldSnapshot,
    WorldSnapshotMetadata,
)


def snapshot(
    identifier: str = "snapshot-current",
    *,
    world_id: str = "world-1",
    game_date: int = 20,
    complete: bool = True,
    capability_fingerprint: str = "fingerprint",
    save_generation: int = 2,
    observer_company_id: str | None = "company-1",
    company: Company | None = None,
    vehicles: tuple[Vehicle, ...] = (),
) -> WorldSnapshot:
    return WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id=identifier,
            world_id=world_id,
            game="openttd",
            game_version="15.3",
            game_date=game_date,
            capture_started_game_date=game_date,
            capture_completed_game_date=game_date,
            complete=complete,
            capability_fingerprint=capability_fingerprint,
            save_generation=save_generation,
            bridge_sequence=10,
            captured_at=datetime.now(UTC),
            observer_company_id=observer_company_id,
        ),
        coverage=tuple(
            CapabilityCoverage(category=category, status=CoverageStatus.PARTIAL)
            for category in (
                "companies",
                "vehicles",
                "stations",
                "routes",
                "towns",
                "industries",
                "cargo",
            )
        ),
        companies=(company or Company(id="company-1", name="Company", cash=100, loan=0),),
        vehicles=vehicles,
    )
