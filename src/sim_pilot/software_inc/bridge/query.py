"""Deterministic terminal queries over one Software Inc. snapshot."""

from __future__ import annotations

import json

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncCompatibilityError

SEMANTIC_SURFACES = (
    "applicants",
    "build_catalog",
    "build_ui",
    "company",
    "contract_market",
    "contract_results",
    "contract_ui",
    "education",
    "education_ui",
    "employees",
    "finances",
    "infrastructure",
    "office_ui",
    "offices",
    "product_catalog",
    "product_ui",
    "products",
    "staffing_ui",
    "teams",
    "work_items",
)
SURFACE_ALIASES = {
    "applicant": "applicants",
    "catalog": "build_catalog",
    "build": "build_ui",
    "employee": "employees",
    "contract": "contract_market",
    "contract_result": "contract_results",
    "course": "education",
    "education_state": "education_ui",
    "infrastructure_item": "infrastructure",
    "office": "offices",
    "product_feature": "product_catalog",
    "product_type": "product_catalog",
    "product_configuration": "product_ui",
    "product": "products",
    "staffing": "staffing_ui",
    "team": "teams",
    "work_item": "work_items",
}


def surface_from(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    normalized = name.strip().casefold().replace("-", "_")
    normalized = SURFACE_ALIASES.get(normalized, normalized)
    if normalized not in SEMANTIC_SURFACES:
        raise SoftwareIncCompatibilityError(
            f"unknown Software Inc. surface {name!r}; choose {', '.join(SEMANTIC_SURFACES)}"
        )
    surface = next(
        (item for item in snapshot.surfaces if item.coverage.surface == normalized), None
    )
    if surface is None or surface.coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        detail = (
            "surface omitted"
            if surface is None
            else surface.coverage.detail or surface.coverage.status.value
        )
        raise SoftwareIncCompatibilityError(f"{normalized} is not observable: {detail}")
    return surface


def entity_from(snapshot: GameSnapshot, surface_name: str, reference: str) -> ObservedEntity:
    surface = surface_from(snapshot, surface_name)
    wanted = reference.strip().casefold()
    matches = [entity for entity in surface.entities if wanted in _references(entity)]
    if not matches:
        raise SoftwareIncCompatibilityError(
            f"no {surface.coverage.surface} entity matches {reference!r}"
        )
    if len(matches) > 1:
        raise SoftwareIncCompatibilityError(
            f"{reference!r} is ambiguous: {', '.join(item.entity_id for item in matches)}"
        )
    return matches[0]


def render_surface(surface: ObservationSurface) -> str:
    header = (
        f"{surface.coverage.surface}: {len(surface.entities)} entities "
        f"({surface.coverage.status.value})"
    )
    labels = [
        f"- {item.entity_id} — {item.values.get('name', item.entity_type)}"
        for item in surface.entities
    ]
    return "\n".join((header, *labels))


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
