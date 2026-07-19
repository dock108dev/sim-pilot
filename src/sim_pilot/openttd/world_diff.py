"""Deterministic typed differences between compatible world snapshots."""

from __future__ import annotations

from typing import Protocol, TypeVar

from sim_pilot.domain.world import (
    CoverageChanged,
    CoverageStatus,
    EntityAdded,
    EntityRemoved,
    FieldChanged,
    WorldChange,
    WorldSnapshot,
)


class Identified(Protocol):
    id: str


EntityT = TypeVar("EntityT", bound=Identified)


def diff_world(previous: WorldSnapshot, current: WorldSnapshot) -> WorldSnapshot:
    if previous.metadata.world_id != current.metadata.world_id:
        raise ValueError("cannot diff snapshots from different worlds")
    changes: list[WorldChange] = []
    prior_coverage = {item.category: item.status for item in previous.coverage}
    current_coverage = {item.category: item.status for item in current.coverage}
    for category in sorted(set(prior_coverage) & set(current_coverage)):
        before = prior_coverage[category]
        after = current_coverage[category]
        if before is not after:
            changes.append(CoverageChanged(category=category, before=before, after=after))

    _compare(
        changes,
        "company",
        previous.companies,
        current.companies,
        ("name", "cash", "loan", "company_value", "income", "expenses", "station_count"),
        _complete(previous, current, "companies"),
    )
    _compare(
        changes,
        "town",
        previous.towns,
        current.towns,
        ("name", "population", "station_count", "growth_rate_days", "growth_state"),
        _complete(previous, current, "towns"),
    )
    _compare(
        changes,
        "industry",
        previous.industries,
        current.industries,
        ("name", "type", "nearby_station_count"),
        _complete(previous, current, "industries"),
    )
    _compare(
        changes,
        "station",
        previous.stations,
        current.stations,
        ("name", "vehicle_count"),
        _complete(previous, current, "stations"),
    )
    _compare(
        changes,
        "vehicle",
        previous.vehicles,
        current.vehicles,
        ("name", "running_state", "profit_this_year", "profit_last_year", "route_id", "in_depot"),
        _complete(previous, current, "vehicles"),
    )
    _compare(
        changes,
        "route",
        previous.routes,
        current.routes,
        ("estimated_distance", "inferred_route_type"),
        _complete(previous, current, "routes"),
    )
    return current.model_copy(
        update={
            "changes_from_snapshot_id": previous.metadata.snapshot_id,
            "changes": tuple(sorted(changes, key=_sort_key)),
        }
    )


def _compare(
    changes: list[WorldChange],
    entity_type: str,
    previous: tuple[EntityT, ...],
    current: tuple[EntityT, ...],
    fields: tuple[str, ...],
    complete: bool,
) -> None:
    before = {_identifier(item): item for item in previous}
    after = {_identifier(item): item for item in current}
    if complete:
        changes.extend(
            EntityAdded(entity_type=entity_type, entity_id=entity_id)
            for entity_id in sorted(after.keys() - before.keys())
        )
        changes.extend(
            EntityRemoved(entity_type=entity_type, entity_id=entity_id)
            for entity_id in sorted(before.keys() - after.keys())
        )
    for entity_id in sorted(before.keys() & after.keys()):
        for field in fields:
            prior_value = getattr(before[entity_id], field)
            current_value = getattr(after[entity_id], field)
            if prior_value != current_value:
                changes.append(
                    FieldChanged(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field=field,
                        before=prior_value,
                        after=current_value,
                    )
                )


def _complete(previous: WorldSnapshot, current: WorldSnapshot, category: str) -> bool:
    if not previous.metadata.complete or not current.metadata.complete:
        return False
    prior = next((item.status for item in previous.coverage if item.category == category), None)
    after = next((item.status for item in current.coverage if item.category == category), None)
    return prior is not CoverageStatus.UNAVAILABLE and after is not CoverageStatus.UNAVAILABLE


def _identifier(item: Identified) -> str:
    return item.id


def _sort_key(change: WorldChange) -> tuple[str, str, str, str]:
    return (
        change.change_type,
        str(getattr(change, "entity_type", getattr(change, "category", ""))),
        str(getattr(change, "entity_id", "")),
        str(getattr(change, "field", "")),
    )
