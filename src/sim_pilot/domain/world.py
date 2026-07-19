"""Game-neutral, immutable world-observation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WorldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class CoverageStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CoverageReason(StrEnum):
    NONE = "none"
    GAME_API_LIMITATION = "game_api_limitation"
    BRIDGE_LIMITATION = "bridge_limitation"
    ADAPTER_LIMITATION = "adapter_limitation"
    NOT_APPLICABLE = "not_applicable"
    CAPTURE_INCOMPLETE = "capture_incomplete"


class CapabilityCoverage(WorldModel):
    category: str = Field(min_length=1)
    status: CoverageStatus
    reason: CoverageReason = CoverageReason.NONE
    fields: tuple[str, ...] = ()
    detail: str | None = None


class Coordinates(WorldModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class CargoFlowScope(StrEnum):
    WORLD = "world"
    COMPANY = "company"
    TOWN = "town"
    INDUSTRY = "industry"
    STATION = "station"
    VEHICLE = "vehicle"


class CargoFlow(WorldModel):
    cargo_id: str = Field(min_length=1)
    cargo_type: str = Field(min_length=1)
    scope: CargoFlowScope
    entity_id: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    waiting: int | None = Field(default=None, ge=0)
    produced: int | None = Field(default=None, ge=0)
    accepted: bool | None = None
    transported: int | None = Field(default=None, ge=0)
    transported_percent: int | None = Field(default=None, ge=0, le=100)
    period: str | None = None


class Town(WorldModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    population: int = Field(ge=0)
    coordinates: Coordinates
    authority_rating: int | None = Field(default=None, ge=-1000, le=1000)
    station_count: int | None = Field(default=None, ge=0)
    served_cargo_ids: tuple[str, ...] = ()
    cargo_flows: tuple[CargoFlow, ...] = ()
    growth_rate_days: int | None = Field(default=None, ge=0)
    growth_state: str | None = None


class Industry(WorldModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    coordinates: Coordinates
    production: tuple[CargoFlow, ...] = ()
    accepted_cargo_ids: tuple[str, ...] = ()
    produced_cargo_ids: tuple[str, ...] = ()
    nearby_station_ids: tuple[str, ...] = ()
    nearby_station_count: int | None = Field(default=None, ge=0)
    owner_id: str | None = None


class VehicleCounts(WorldModel):
    rail: int = Field(default=0, ge=0)
    road: int = Field(default=0, ge=0)
    water: int = Field(default=0, ge=0)
    air: int = Field(default=0, ge=0)


class Company(WorldModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cash: int
    loan: int = Field(ge=0)
    company_value: int | None = None
    income: int | None = None
    expenses: int | None = None
    vehicle_counts: VehicleCounts = VehicleCounts()
    station_count: int = Field(default=0, ge=0)
    headquarters: Coordinates | None = None
    is_ai: bool | None = None
    performance_rating: int | None = Field(default=None, ge=0)


class VehicleOrderKind(StrEnum):
    STATION = "station"
    DEPOT = "depot"
    WAYPOINT = "waypoint"
    CONDITIONAL = "conditional"
    OTHER = "other"


class VehicleOrder(WorldModel):
    index: int = Field(ge=0)
    kind: VehicleOrderKind
    destination_id: str | None = None
    destination_coordinates: Coordinates | None = None
    flags: int | None = Field(default=None, ge=0)


class Vehicle(WorldModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    subtype: str | None = None
    name: str = Field(min_length=1)
    age_days: int = Field(ge=0)
    profit_this_year: int
    profit_last_year: int
    running_state: str = Field(min_length=1)
    coordinates: Coordinates | None
    current_order: VehicleOrder | None = None
    orders: tuple[VehicleOrder, ...] = ()
    route_id: str | None = None
    in_depot: bool
    owner_id: str = Field(min_length=1)


class Station(WorldModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    coordinates: Coordinates
    facilities: tuple[str, ...] = ()
    accepted_cargo_ids: tuple[str, ...] = ()
    waiting_cargo: tuple[CargoFlow, ...] = ()
    served_industry_ids: tuple[str, ...] = ()
    served_town_ids: tuple[str, ...] = ()
    vehicle_count: int = Field(default=0, ge=0)


class Route(WorldModel):
    id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    vehicle_ids: tuple[str, ...]
    ordered_station_ids: tuple[str, ...]
    estimated_distance: int | None = Field(default=None, ge=0)
    distance_method: str | None = None
    cargo_ids: tuple[str, ...] = ()
    inferred_route_type: str = Field(min_length=1)


class EntityAdded(WorldModel):
    change_type: Literal["entity_added"] = "entity_added"
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class EntityRemoved(WorldModel):
    change_type: Literal["entity_removed"] = "entity_removed"
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class FieldChanged(WorldModel):
    change_type: Literal["field_changed"] = "field_changed"
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    before: str | int | bool | None
    after: str | int | bool | None


class CoverageChanged(WorldModel):
    change_type: Literal["coverage_changed"] = "coverage_changed"
    category: str = Field(min_length=1)
    before: CoverageStatus
    after: CoverageStatus


WorldChange = Annotated[
    EntityAdded | EntityRemoved | FieldChanged | CoverageChanged,
    Field(discriminator="change_type"),
]


class WorldSnapshotMetadata(WorldModel):
    snapshot_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    game: str = Field(min_length=1)
    game_version: str = Field(min_length=1)
    game_date: int = Field(ge=0)
    capture_started_game_date: int = Field(ge=0)
    capture_completed_game_date: int = Field(ge=0)
    complete: bool
    capability_fingerprint: str = Field(min_length=1)
    save_generation: int = Field(ge=0)
    bridge_sequence: int = Field(ge=1)
    captured_at: AwareDatetime
    observer_company_id: str | None = Field(default=None, min_length=1)


class WorldSnapshot(WorldModel):
    metadata: WorldSnapshotMetadata
    coverage: tuple[CapabilityCoverage, ...]
    companies: tuple[Company, ...] = ()
    towns: tuple[Town, ...] = ()
    industries: tuple[Industry, ...] = ()
    stations: tuple[Station, ...] = ()
    vehicles: tuple[Vehicle, ...] = ()
    routes: tuple[Route, ...] = ()
    cargo_summary: tuple[CargoFlow, ...] = ()
    changes_from_snapshot_id: str | None = None
    changes: tuple[WorldChange, ...] = ()
