"""Deterministic route inference from canonical vehicle orders."""

from __future__ import annotations

import hashlib

from sim_pilot.domain.world import Coordinates, Route, Station, Vehicle


def infer_routes(
    vehicles: tuple[Vehicle, ...], stations: tuple[Station, ...]
) -> tuple[tuple[Vehicle, ...], tuple[Route, ...]]:
    station_by_id = {station.id: station for station in stations}
    groups: dict[tuple[str, str, tuple[str, ...]], list[Vehicle]] = {}
    for vehicle in vehicles:
        signature = _normalized_signature(vehicle)
        if signature:
            groups.setdefault((vehicle.owner_id, vehicle.type, signature), []).append(vehicle)
    routes: list[Route] = []
    route_for_vehicle: dict[str, str] = {}
    for (owner_id, vehicle_type, signature), members in sorted(groups.items()):
        digest = hashlib.sha256(
            "|".join((owner_id, vehicle_type, *signature)).encode()
        ).hexdigest()[:24]
        route_id = f"route:{digest}"
        station_ids = tuple(
            token.split("|", 2)[1] for token in signature if token.startswith("station|")
        )
        routes.append(
            Route(
                id=route_id,
                owner_id=owner_id,
                vehicle_ids=tuple(sorted(vehicle.id for vehicle in members)),
                ordered_station_ids=station_ids,
                estimated_distance=_route_distance(station_ids, station_by_id),
                distance_method="cyclic_manhattan_between_station_signs" if station_ids else None,
                inferred_route_type=vehicle_type,
            )
        )
        route_for_vehicle.update({vehicle.id: route_id for vehicle in members})
    return (
        tuple(
            vehicle.model_copy(update={"route_id": route_for_vehicle.get(vehicle.id)})
            for vehicle in vehicles
        ),
        tuple(routes),
    )


def _normalized_signature(vehicle: Vehicle) -> tuple[str, ...]:
    tokens = tuple(
        f"{order.kind.value}|"
        f"{order.destination_id or _coordinate_token(order.destination_coordinates)}"
        f"|{order.flags if order.flags is not None else ''}"
        for order in vehicle.orders
    )
    if not tokens:
        return ()
    return min(tokens[index:] + tokens[:index] for index in range(len(tokens)))


def _coordinate_token(value: Coordinates | None) -> str:
    return "none" if value is None else f"{value.x},{value.y}"


def _route_distance(station_ids: tuple[str, ...], stations: dict[str, Station]) -> int | None:
    if len(station_ids) < 2 or any(station_id not in stations for station_id in station_ids):
        return None
    coordinates = [stations[station_id].coordinates for station_id in station_ids]
    pairs = zip(coordinates, coordinates[1:] + coordinates[:1], strict=True)
    return sum(abs(left.x - right.x) + abs(left.y - right.y) for left, right in pairs)
