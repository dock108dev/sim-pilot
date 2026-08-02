"""Strict projections from Software Inc. v9 education surfaces."""

from __future__ import annotations

from decimal import Decimal

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import EmployeeTrainingObservation


def education_duration_months(snapshot: GameSnapshot) -> int:
    surface = require_complete_surface(snapshot, "education")
    rules = [entity for entity in surface.entities if entity.entity_type == "education_rule"]
    if len(rules) != 1:
        raise SoftwareIncUIValidationError("education duration did not resolve exactly once")
    return _integer(rules[0], "duration_months")


def training_candidates(
    snapshot: GameSnapshot, *, team_name: str, role: str, specialization: str
) -> tuple[EmployeeTrainingObservation, ...]:
    education = require_complete_surface(snapshot, "education")
    employees = require_complete_surface(snapshot, "employees")
    by_id = {
        entity.entity_id: entity
        for entity in employees.entities
        if entity.entity_type == "employee"
    }
    result: list[EmployeeTrainingObservation] = []
    for spec in education.entities:
        if spec.entity_type != "employee_specialization":
            continue
        if _text(spec, "team").casefold() != team_name.casefold():
            continue
        if _text(spec, "role").casefold() != role.casefold():
            continue
        if _text(spec, "specialization").casefold() != specialization.casefold():
            continue
        employee_id = _text(spec, "employee_id")
        employee = by_id.get(employee_id)
        if employee is None:
            raise SoftwareIncUIValidationError("education references an unknown employee")
        courses = _split(_text(employee, "courses", empty=True))
        result.append(
            EmployeeTrainingObservation(
                employee_id=employee_id,
                employee_name=_text(employee, "name"),
                team_name=_text(employee, "team"),
                role=role,
                specialization=specialization,
                level=_integer(spec, "level"),
                base_skill=_decimal(employee, "skill_designer"),
                monthly_salary=_decimal(employee, "salary"),
                taking_courses=_boolean(employee, "taking_courses"),
                active_courses=courses,
                one_time_cost=_decimal(spec, "one_time_cost"),
            )
        )
    return tuple(sorted(result, key=lambda item: item.employee_id))


def exact_employee_training(
    snapshot: GameSnapshot, *, employee_id: str, role: str, specialization: str
) -> EmployeeTrainingObservation:
    matches = [
        item
        for item in training_candidates(
            snapshot,
            team_name=_employee_team(snapshot, employee_id),
            role=role,
            specialization=specialization,
        )
        if item.employee_id == employee_id
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError("exact employee education state is unavailable")
    return matches[0]


def current_cash(snapshot: GameSnapshot) -> Decimal:
    surface = _surface(snapshot, "finances")
    if surface.coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        raise SoftwareIncUIValidationError("current finances are not observed")
    if len(surface.entities) != 1:
        raise SoftwareIncUIValidationError("current cash did not resolve exactly once")
    return _decimal(surface.entities[0], "cash")


def team_employee_count(snapshot: GameSnapshot, team_name: str) -> int:
    surface = require_complete_surface(snapshot, "teams")
    matches = [
        entity
        for entity in surface.entities
        if entity.entity_type == "team" and _text(entity, "name").casefold() == team_name.casefold()
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"team {team_name!r} is unavailable or ambiguous")
    return _integer(matches[0], "employee_count")


def assigned_active_work(snapshot: GameSnapshot, team_name: str) -> tuple[str, ...]:
    surface = require_complete_surface(snapshot, "work_items")
    result: list[str] = []
    for entity in surface.entities:
        if entity.entity_type != "work_item" or entity.values.get("done") is True:
            continue
        teams = _split(_text(entity, "assigned_teams", empty=True))
        if team_name.casefold() in {team.casefold() for team in teams}:
            result.append(_text(entity, "name"))
    return tuple(sorted(set(result)))


def require_complete_surface(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    surface = _surface(snapshot, name)
    if surface.coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise SoftwareIncUIValidationError(
            f"{name} is not completely observed: {surface.coverage.detail}"
        )
    return surface


def _surface(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"{name} surface is missing or duplicated")
    return matches[0]


def _employee_team(snapshot: GameSnapshot, employee_id: str) -> str:
    surface = require_complete_surface(snapshot, "employees")
    matches = [
        entity
        for entity in surface.entities
        if entity.entity_type == "employee" and entity.entity_id == employee_id
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError("employee identity is stale or ambiguous")
    return _text(matches[0], "team")


def _text(entity: ObservedEntity, field: str, *, empty: bool = False) -> str:
    value = entity.values.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed text")
    return value


def _decimal(entity: ObservedEntity, field: str) -> Decimal:
    value = entity.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed numeric")
    result = Decimal(str(value))
    if not result.is_finite():
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is invalid")
    return result


def _integer(entity: ObservedEntity, field: str) -> int:
    value = entity.values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an integer")
    return value


def _boolean(entity: ObservedEntity, field: str) -> bool:
    value = entity.values.get(field)
    if not isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not boolean")
    return value


def _split(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split("|") if part)


__all__ = [
    "assigned_active_work",
    "current_cash",
    "education_duration_months",
    "exact_employee_training",
    "require_complete_surface",
    "team_employee_count",
    "training_candidates",
]
