"""Translate bridge-specific entities into canonical world snapshots."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sim_pilot.domain.world import (
    CapabilityCoverage,
    CargoFlow,
    CargoFlowScope,
    Company,
    Coordinates,
    CoverageReason,
    CoverageStatus,
    Industry,
    Station,
    Town,
    Vehicle,
    VehicleCounts,
    VehicleOrder,
    VehicleOrderKind,
    WorldSnapshot,
    WorldSnapshotMetadata,
)
from sim_pilot.openttd.gamescript.messages import BridgeCargoEntity
from sim_pilot.openttd.gamescript.models import BridgeHealth, BridgeWorldSnapshot
from sim_pilot.openttd.models import OpenTTDState
from sim_pilot.openttd.route_inference import infer_routes


def translate_world(
    state: OpenTTDState, health: BridgeHealth, *, captured_at: datetime | None = None
) -> WorldSnapshot | None:
    source = health.world_snapshot
    world_id = health.script_instance_id
    fingerprint = health.capability_fingerprint
    if source is None or world_id is None or fingerprint is None:
        return None
    width = state.map.width
    cargo_ids = {
        item.id: _id(world_id, "cargo", item.id) for item in source.cargos if item.scope == "world"
    }
    flows = tuple(_cargo_flow(item, world_id, cargo_ids) for item in source.cargos)
    by_scope: dict[tuple[str, int], list[CargoFlow]] = defaultdict(list)
    for item, flow in zip(source.cargos, flows, strict=True):
        if item.scope_entity_id is not None:
            by_scope[(item.scope, item.scope_entity_id)].append(flow)
    vehicle_counts = _vehicle_counts(source)
    companies = tuple(
        Company(
            id=_id(world_id, "company", item.id),
            name=item.name,
            cash=state.company.cash if item.id == state.company.company_id else item.cash,
            loan=state.company.loan if item.id == state.company.company_id else item.loan,
            company_value=(
                state.company.company_value_last_quarter
                if item.id == state.company.company_id
                else item.company_value
            ),
            income=item.income,
            expenses=item.expenses,
            vehicle_counts=vehicle_counts.get(item.id, VehicleCounts()),
            station_count=item.station_count,
            headquarters=_coordinates(item.headquarters_tile, width),
            is_ai=state.company.is_ai if item.id == state.company.company_id else None,
            performance_rating=(
                state.company.performance_last_quarter
                if item.id == state.company.company_id
                else item.performance
            ),
        )
        for item in sorted(source.companies, key=lambda value: value.id)
    )
    towns = tuple(
        Town(
            id=_id(world_id, "town", item.id),
            name=item.name,
            population=item.population,
            coordinates=_required_coordinates(item.tile, width),
            authority_rating=item.rating,
            served_cargo_ids=tuple(sorted({flow.cargo_id for flow in by_scope[("town", item.id)]})),
            cargo_flows=tuple(by_scope[("town", item.id)]),
            growth_rate_days=item.growth_rate,
            growth_state="not_growing" if item.growth_rate in {None, 0xFFFF} else "growing",
        )
        for item in sorted(source.towns, key=lambda value: value.id)
    )
    industries = _industries(source, world_id, width, cargo_ids, by_scope)
    stations = _stations(source, world_id, width, by_scope)
    vehicles = _vehicles(source, world_id, width)
    stations, towns, industries = _relationships(stations, towns, industries, vehicles)
    vehicles, routes = infer_routes(vehicles, stations)
    return WorldSnapshot(
        metadata=WorldSnapshotMetadata(
            snapshot_id=source.snapshot_id,
            world_id=world_id,
            game="openttd",
            game_version=state.connection.openttd_version,
            game_date=state.game_date_raw,
            capture_started_game_date=source.capture_started_game_date,
            capture_completed_game_date=source.capture_completed_game_date,
            complete=source.complete,
            capability_fingerprint=fingerprint,
            save_generation=0 if health.snapshot is None else health.snapshot.save_generation,
            bridge_sequence=health.last_sequence or 1,
            captured_at=captured_at or datetime.now(UTC),
        ),
        coverage=_coverage(),
        companies=companies,
        towns=towns,
        industries=industries,
        stations=stations,
        vehicles=vehicles,
        routes=routes,
        cargo_summary=flows,
    )


def _industries(
    source: BridgeWorldSnapshot,
    world_id: str,
    width: int,
    cargo_ids: dict[int, str],
    flows: dict[tuple[str, int], list[CargoFlow]],
) -> tuple[Industry, ...]:
    return tuple(
        Industry(
            id=_id(world_id, "industry", item.id),
            type=f"industry_type:{item.industry_type}",
            name=item.name,
            coordinates=_required_coordinates(item.tile, width),
            production=tuple(flows[("industry", item.id)]),
            accepted_cargo_ids=tuple(
                cargo_ids.get(value, _id(world_id, "cargo", value))
                for value in item.accepted_cargo_ids
            ),
            produced_cargo_ids=tuple(
                cargo_ids.get(value, _id(world_id, "cargo", value))
                for value in item.produced_cargo_ids
            ),
            nearby_station_count=item.nearby_station_count,
        )
        for item in sorted(source.industries, key=lambda value: value.id)
    )


def _stations(
    source: BridgeWorldSnapshot,
    world_id: str,
    width: int,
    flows: dict[tuple[str, int], list[CargoFlow]],
) -> tuple[Station, ...]:
    return tuple(
        Station(
            id=_id(world_id, "station", item.id),
            name=item.name,
            owner_id=_id(world_id, "company", item.owner),
            coordinates=_required_coordinates(item.tile, width),
            facilities=item.facilities,
            waiting_cargo=tuple(flows[("station", item.id)]),
        )
        for item in sorted(source.stations, key=lambda value: value.id)
    )


def _vehicles(source: BridgeWorldSnapshot, world_id: str, width: int) -> tuple[Vehicle, ...]:
    orders_by_vehicle: dict[int, list[VehicleOrder]] = defaultdict(list)
    station_ids = {item.id for item in source.stations}
    for item in sorted(source.orders, key=lambda value: (value.vehicle_id, value.index)):
        destination_id = (
            _id(world_id, "station", item.destination_station_id)
            if item.destination_station_id in station_ids
            else None
        )
        orders_by_vehicle[item.vehicle_id].append(
            VehicleOrder(
                index=item.index,
                kind=VehicleOrderKind(item.kind),
                destination_id=destination_id,
                destination_coordinates=_coordinates(item.destination_tile, width),
                flags=item.flags,
            )
        )
    types = {0: "rail", 1: "road", 2: "water", 3: "air"}
    states = {
        0: "running",
        1: "stopped",
        2: "in_depot",
        3: "at_station",
        4: "broken",
        5: "crashed",
    }
    values: list[Vehicle] = []
    for item in sorted(source.vehicles, key=lambda value: value.id):
        orders = tuple(orders_by_vehicle[item.id])
        current = next((order for order in orders if order.index == item.current_order_index), None)
        values.append(
            Vehicle(
                id=_id(world_id, "vehicle", item.id),
                type=types.get(item.vehicle_type, f"unknown:{item.vehicle_type}"),
                subtype=f"engine:{item.engine_type}",
                name=item.name,
                age_days=item.age_days,
                profit_this_year=item.profit_this_year,
                profit_last_year=item.profit_last_year,
                running_state=states.get(item.state, f"unknown:{item.state}"),
                coordinates=_coordinates(item.tile, width),
                current_order=current,
                orders=orders,
                in_depot=item.in_depot,
                owner_id=_id(world_id, "company", item.owner),
            )
        )
    return tuple(values)


def _relationships(
    stations: tuple[Station, ...],
    towns: tuple[Town, ...],
    industries: tuple[Industry, ...],
    vehicles: tuple[Vehicle, ...],
) -> tuple[tuple[Station, ...], tuple[Town, ...], tuple[Industry, ...]]:
    vehicle_counts: Counter[str] = Counter()
    for vehicle in vehicles:
        vehicle_counts.update(
            {order.destination_id for order in vehicle.orders if order.destination_id is not None}
        )
    stations = tuple(
        station.model_copy(
            update={
                "served_town_ids": tuple(
                    town.id
                    for town in towns
                    if _distance(station.coordinates, town.coordinates) <= 12
                ),
                "served_industry_ids": tuple(
                    industry.id
                    for industry in industries
                    if _distance(station.coordinates, industry.coordinates) <= 8
                ),
                "vehicle_count": vehicle_counts[station.id],
            }
        )
        for station in stations
    )
    towns = tuple(
        town.model_copy(
            update={
                "station_count": sum(town.id in station.served_town_ids for station in stations)
            }
        )
        for town in towns
    )
    industries = tuple(
        industry.model_copy(
            update={
                "nearby_station_ids": tuple(
                    station.id for station in stations if industry.id in station.served_industry_ids
                )
            }
        )
        for industry in industries
    )
    return stations, towns, industries


def _vehicle_counts(source: BridgeWorldSnapshot) -> dict[int, VehicleCounts]:
    counts: dict[int, Counter[int]] = defaultdict(Counter)
    for vehicle in source.vehicles:
        counts[vehicle.owner][vehicle.vehicle_type] += 1
    return {
        owner: VehicleCounts(rail=value[0], road=value[1], water=value[2], air=value[3])
        for owner, value in counts.items()
    }


def _cargo_flow(item: BridgeCargoEntity, world_id: str, ids: dict[int, str]) -> CargoFlow:
    return CargoFlow(
        cargo_id=ids.get(item.id, _id(world_id, "cargo", item.id)),
        cargo_type=item.name,
        scope=CargoFlowScope(item.scope),
        entity_id=(
            None
            if item.scope_entity_id is None
            else _id(world_id, item.scope, item.scope_entity_id)
        ),
        waiting=item.waiting,
        produced=item.produced,
        accepted=item.accepted,
        transported=item.transported,
        transported_percent=item.transported_percent,
        period=None if item.scope == "world" else "last_economy_month",
    )


def _coverage() -> tuple[CapabilityCoverage, ...]:
    partial = CoverageStatus.PARTIAL
    bridge = CoverageReason.BRIDGE_LIMITATION
    adapter = CoverageReason.ADAPTER_LIMITATION
    return (
        CapabilityCoverage(category="server_metadata", status=CoverageStatus.AVAILABLE),
        CapabilityCoverage(category="map_metadata", status=partial, reason=bridge),
        CapabilityCoverage(category="companies", status=partial, reason=bridge),
        CapabilityCoverage(category="towns", status=partial, reason=adapter),
        CapabilityCoverage(category="industries", status=partial, reason=adapter),
        CapabilityCoverage(category="stations", status=partial, reason=adapter),
        CapabilityCoverage(category="vehicles", status=partial, reason=bridge),
        CapabilityCoverage(category="routes", status=partial, reason=adapter),
        CapabilityCoverage(category="cargo", status=partial, reason=adapter),
        CapabilityCoverage(category="tiles", status=CoverageStatus.UNAVAILABLE, reason=bridge),
        CapabilityCoverage(category="terrain", status=CoverageStatus.UNAVAILABLE, reason=bridge),
        CapabilityCoverage(
            category="infrastructure", status=CoverageStatus.UNAVAILABLE, reason=bridge
        ),
        CapabilityCoverage(category="economy", status=partial, reason=bridge),
        CapabilityCoverage(
            category="native_events", status=CoverageStatus.UNAVAILABLE, reason=bridge
        ),
    )


def _id(world_id: str, kind: str, source_id: int) -> str:
    digest = hashlib.sha256(f"{world_id}|{kind}|{source_id}".encode()).hexdigest()[:24]
    return f"{kind}:{digest}"


def _coordinates(tile: int | None, width: int) -> Coordinates | None:
    return None if tile is None else Coordinates(x=tile % width, y=tile // width)


def _required_coordinates(tile: int, width: int) -> Coordinates:
    return Coordinates(x=tile % width, y=tile // width)


def _distance(left: Coordinates, right: Coordinates) -> int:
    return abs(left.x - right.x) + abs(left.y - right.y)
