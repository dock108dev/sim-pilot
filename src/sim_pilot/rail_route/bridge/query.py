"""Deterministic terminal queries over one immutable Rail Route bridge snapshot."""

from __future__ import annotations

import json

from sim_pilot.game_bridge import (
    CoverageStatus,
    GameSnapshot,
    ObservationSurface,
    ObservedEntity,
)

from .errors import RailRouteBridgeObservationError

SEMANTIC_SURFACES = (
    "incoming_traffic",
    "platforms",
    "routes",
    "signals",
    "stations",
    "switches",
    "track_occupancy",
    "trains",
)


def surface_from(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    normalized = name.strip().casefold().replace("-", "_")
    if normalized not in SEMANTIC_SURFACES:
        raise RailRouteBridgeObservationError(
            f"unknown Rail Route surface {name!r}; choose {', '.join(SEMANTIC_SURFACES)}"
        )
    surface = next(
        (item for item in snapshot.surfaces if item.coverage.surface == normalized), None
    )
    if surface is None:
        raise RailRouteBridgeObservationError(
            f"{normalized} is not observable: bridge snapshot omitted the surface"
        )
    if surface.coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        detail = surface.coverage.detail or surface.coverage.status.value
        raise RailRouteBridgeObservationError(f"{normalized} is not observable: {detail}")
    return surface


def entity_from(snapshot: GameSnapshot, surface_name: str, reference: str) -> ObservedEntity:
    surface = surface_from(snapshot, surface_name)
    wanted = reference.strip().casefold()
    matches = [entity for entity in surface.entities if wanted in _references(entity)]
    if not matches:
        raise RailRouteBridgeObservationError(
            f"no {surface.coverage.surface} entity matches {reference!r}"
        )
    if len(matches) > 1:
        identities = ", ".join(item.entity_id for item in matches)
        raise RailRouteBridgeObservationError(
            f"{reference!r} is ambiguous in {surface.coverage.surface}: {identities}"
        )
    return matches[0]


def render_surface(surface: ObservationSurface) -> str:
    header = (
        f"{surface.coverage.surface}: {len(surface.entities)} entities "
        f"({surface.coverage.status.value})"
    )
    if not surface.entities:
        return header
    return "\n".join([header, *(f"- {_label(entity)}" for entity in surface.entities)])


def render_entity(entity: ObservedEntity) -> str:
    values = json.dumps(entity.values, sort_keys=True, indent=2)
    return f"{entity.entity_type} {entity.entity_id}\n{values}"


def _references(entity: ObservedEntity) -> set[str]:
    values = {
        value.casefold()
        for value in entity.values.values()
        if isinstance(value, str) and value.strip()
    }
    values.add(entity.entity_id.casefold())
    return values


def _label(entity: ObservedEntity) -> str:
    for key in ("reporting_number", "name", "display_name", "friendly_name", "uuid"):
        value = entity.values.get(key)
        if isinstance(value, str) and value and value != entity.entity_id:
            return f"{entity.entity_id} — {value}"
    return entity.entity_id
