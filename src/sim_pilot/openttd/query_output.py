"""Readable terminal views over canonical world snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sim_pilot.domain.world import WorldChange, WorldSnapshot


def render_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render a small dependency-free table with deterministic column widths."""
    materialized = [[str(value) for value in row] for row in rows]
    if not materialized:
        return "No records."
    widths = [len(header) for header in headers]
    for row in materialized:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    header = "  ".join(value.ljust(widths[index]) for index, value in enumerate(headers))
    rule = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in materialized
    ]
    return "\n".join((header, rule, *body))


def _short(identifier: str | None) -> str:
    if identifier is None:
        return "-"
    return identifier if len(identifier) <= 18 else f"{identifier[:8]}…{identifier[-8:]}"


def _coordinates(value: object) -> str:
    if value is None:
        return "-"
    return f"{value.x},{value.y}"  # type: ignore[attr-defined]


def render_world_summary(world: WorldSnapshot) -> str:
    metadata = world.metadata
    coverage = ", ".join(f"{item.category}={item.status.value}" for item in world.coverage)
    return "\n".join(
        (
            f"Snapshot: {metadata.snapshot_id}",
            f"World: {metadata.world_id}",
            f"Game: {metadata.game} {metadata.game_version} at date {metadata.game_date}",
            f"Complete: {str(metadata.complete).lower()}",
            "Entities: "
            f"{len(world.companies)} companies, {len(world.towns)} towns, "
            f"{len(world.industries)} industries, {len(world.stations)} stations, "
            f"{len(world.vehicles)} vehicles, {len(world.routes)} routes",
            f"Coverage: {coverage}",
        )
    )


def render_world_collection(world: WorldSnapshot, collection: str) -> str:
    if collection == "towns":
        return render_table(
            ("ID", "NAME", "POPULATION", "LOCATION", "STATIONS", "GROWTH"),
            (
                (
                    _short(item.id),
                    item.name,
                    item.population,
                    _coordinates(item.coordinates),
                    item.station_count if item.station_count is not None else "-",
                    item.growth_state or "-",
                )
                for item in world.towns
            ),
        )
    if collection == "industries":
        return render_table(
            ("ID", "TYPE", "NAME", "LOCATION", "PRODUCES", "NEARBY"),
            (
                (
                    _short(item.id),
                    item.type,
                    item.name,
                    _coordinates(item.coordinates),
                    ",".join(item.produced_cargo_ids) or "-",
                    item.nearby_station_count if item.nearby_station_count is not None else "-",
                )
                for item in world.industries
            ),
        )
    if collection == "stations":
        return render_table(
            ("ID", "NAME", "LOCATION", "FACILITIES", "WAITING", "VEHICLES"),
            (
                (
                    _short(item.id),
                    item.name,
                    _coordinates(item.coordinates),
                    ",".join(item.facilities) or "-",
                    sum(flow.waiting or 0 for flow in item.waiting_cargo),
                    item.vehicle_count,
                )
                for item in world.stations
            ),
        )
    if collection == "vehicles":
        return render_table(
            ("ID", "TYPE", "NAME", "STATE", "LOCATION", "PROFIT", "ROUTE"),
            (
                (
                    _short(item.id),
                    item.type,
                    item.name,
                    item.running_state,
                    _coordinates(item.coordinates),
                    item.profit_this_year,
                    _short(item.route_id),
                )
                for item in world.vehicles
            ),
        )
    if collection == "company":
        return render_table(
            ("ID", "NAME", "CASH", "LOAN", "VALUE", "VEHICLES", "STATIONS", "AI"),
            (
                (
                    _short(item.id),
                    item.name,
                    item.cash,
                    item.loan,
                    item.company_value if item.company_value is not None else "-",
                    sum(item.vehicle_counts.model_dump().values()),
                    item.station_count,
                    item.is_ai if item.is_ai is not None else "-",
                )
                for item in world.companies
            ),
        )
    if collection == "routes":
        return render_table(
            ("ID", "TYPE", "VEHICLES", "STATIONS", "DISTANCE", "CARGO"),
            (
                (
                    _short(item.id),
                    item.inferred_route_type,
                    len(item.vehicle_ids),
                    len(item.ordered_station_ids),
                    item.estimated_distance if item.estimated_distance is not None else "-",
                    ",".join(item.cargo_ids) or "-",
                )
                for item in world.routes
            ),
        )
    raise ValueError(f"unsupported world collection: {collection}")


def render_world_changes(changes: Sequence[WorldChange]) -> str:
    def row(change: WorldChange) -> tuple[object, ...]:
        data = change.model_dump(mode="json")
        return (
            data["change_type"],
            data.get("entity_type", data.get("category", "-")),
            _short(data.get("entity_id")),
            data.get("field", "-"),
            data.get("before", "-"),
            data.get("after", "-"),
        )

    return render_table(
        ("CHANGE", "ENTITY", "ID", "FIELD", "BEFORE", "AFTER"),
        (row(change) for change in changes),
    )
