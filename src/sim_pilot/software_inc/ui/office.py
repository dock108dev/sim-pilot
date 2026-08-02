"""Software Inc. 1.8.41 office-readiness projection and bounded intent contracts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import (
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import SoftwareIncUIAction, SoftwareIncUIObservation
from .workstation import select_workstation_catalog


class OfficeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SupportedEmployeeRole(StrEnum):
    LEAD = "Lead"
    PROGRAMMER = "Programmer"
    DESIGNER = "Designer"
    ARTIST = "Artist"
    SERVICE = "Service"


class OfficeIntent(OfficeModel):
    schema_version: Literal[1] = 1
    action: Literal[
        SoftwareIncUIAction.SET_TEAM_WORKING_HOURS,
        SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE,
    ]
    team_name: str = Field(min_length=1, max_length=64)
    work_start: Decimal | None = Field(default=None, ge=0, lt=24)
    work_end: Decimal | None = Field(default=None, gt=0, le=24)
    employee_name: str | None = Field(default=None, min_length=1, max_length=256)
    role: SupportedEmployeeRole | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> OfficeIntent:
        schedule = self.action is SoftwareIncUIAction.SET_TEAM_WORKING_HOURS
        if schedule != (self.work_start is not None and self.work_end is not None):
            raise ValueError("working-hours intent requires start and end")
        if schedule and self.work_start is not None and self.work_end is not None:
            if (
                self.work_start != self.work_start.to_integral_value()
                or self.work_end != self.work_end.to_integral_value()
            ):
                raise ValueError("the verified schedule UI supports whole-hour values only")
            if self.work_end <= self.work_start:
                raise ValueError("working-hours end must follow start")
            if self.work_end - self.work_start > Decimal("12"):
                raise ValueError("working-hours duration must not exceed 12 hours")
        if (not schedule) != (self.employee_name is not None and self.role is not None):
            raise ValueError("role intent requires one employee and one supported role")
        return self


class RoomReadiness(OfficeModel):
    room_id: str
    floor: int
    assigned_teams: tuple[str, ...]
    assignable_workstations: int = Field(ge=0)
    valid_workstations: int = Field(ge=0)
    available_workstations: int = Field(ge=0)
    total_furniture: int = Field(ge=0)
    major_problem: bool
    problem_count: int = Field(ge=0)
    is_lit: bool
    environment: Decimal
    temperature: Decimal
    acoustics: Decimal


class EquipmentReadiness(OfficeModel):
    equipment_id: str
    room_id: str
    name: str
    assignable: bool
    needs_chair: bool
    actions: tuple[str, ...]
    categories: tuple[str, ...]
    function_category: str
    valid: bool
    blocked: bool
    owner_employee_id: str | None = None
    owner_employee_name: str | None = None
    one_time_cost: Decimal = Field(ge=0)
    current_wattage: Decimal = Field(ge=0)
    computer_power: Decimal = Field(ge=0)
    comfort: Decimal
    environment: Decimal


class ServerReadiness(OfficeModel):
    server_id: str
    name: str
    display_name: str
    is_cloud: bool
    available: Decimal
    broken: bool
    server_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    recurring_cost: Decimal = Field(ge=0)
    total_power: Decimal = Field(ge=0)


class TeamOfficeReadiness(OfficeModel):
    schema_version: Literal[1] = 1
    team_id: str
    team_name: str
    employee_count: int = Field(ge=0)
    work_start: Decimal
    work_end: Decimal
    current_capacity: int = Field(ge=0)
    required_capacity: int = Field(ge=0)
    missing_workstations: int = Field(ge=0)
    assigned_rooms: tuple[RoomReadiness, ...]
    assigned_equipment: tuple[EquipmentReadiness, ...]
    cheaper_existing_capacity: tuple[str, ...]
    exact_missing_resource: str | None = None
    expected_benefit: str
    one_time_cost: Decimal | None = Field(default=None, ge=0)
    recurring_cost: Decimal | None = Field(default=None, ge=0)
    observed_cash: Decimal | None = None
    cash_reserve_after_purchase: Decimal | None = None
    servers: tuple[ServerReadiness, ...]
    source_control_required: Literal[False] = False
    material_unknowns: tuple[str, ...]


class OfficeOperationResult(OfficeModel):
    schema_version: Literal[1] = 1
    intent: OfficeIntent
    before: SoftwareIncUIObservation
    after: SoftwareIncUIObservation
    gestures_sent: int = Field(ge=0)
    cycles: int = Field(ge=1)
    dry_run: bool
    verified: bool
    message: str = Field(min_length=1, max_length=2048)


class OfficePurchaseApproval(OfficeModel):
    """Exact authority contract for later visible-UI equipment commitments."""

    schema_version: Literal[1] = 1
    item_name: str = Field(min_length=1, max_length=256)
    quantity: int = Field(gt=0, le=100)
    unit_price: Decimal = Field(gt=0)
    total_price: Decimal = Field(gt=0)
    projected_cash_after: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    recurring_monthly_cost: Decimal = Field(ge=0)
    recurring_cost_authorized: bool

    @model_validator(mode="after")
    def validate_exact_commitment(self) -> OfficePurchaseApproval:
        if self.total_price != self.unit_price * self.quantity:
            raise ValueError("total price must exactly equal unit price times quantity")
        if self.projected_cash_after < self.minimum_cash_reserve:
            raise ValueError("purchase would violate the approved cash reserve")
        if self.recurring_monthly_cost > 0 and not self.recurring_cost_authorized:
            raise ValueError("recurring infrastructure cost needs separate authority")
        return self


_HOURS = (
    re.compile(
        r"^(?:set|configure)\s+(?P<team>.+?)\s+(?:team\s+)?working\s+hours\s+"
        r"(?:to|from)\s+(?P<start>\d{1,2}(?::\d{2})?)\s*(?:-|to)\s*"
        r"(?P<end>\d{1,2}(?::\d{2})?)$",
        re.IGNORECASE,
    ),
)
_ROLE = (
    re.compile(
        r"^(?:assign|set)\s+(?P<employee>.+?)\s+(?:the\s+)?(?:employee\s+)?role\s+"
        r"(?P<role>lead|programmer|designer|artist|service)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:assign|set)\s+(?P<employee>.+?)\s+(?:as|to)\s+"
        r"(?P<role>lead|programmer|designer|artist|service)\s+(?:for|on)\s+(?P<team>.+)$",
        re.IGNORECASE,
    ),
)


def parse_office_intent(instruction: str, *, default_team: str | None = None) -> OfficeIntent:
    normalized = " ".join(instruction.strip().split())
    for pattern in _HOURS:
        match = pattern.fullmatch(normalized)
        if match:
            return OfficeIntent(
                action=SoftwareIncUIAction.SET_TEAM_WORKING_HOURS,
                team_name=match.group("team"),
                work_start=_hour(match.group("start")),
                work_end=_hour(match.group("end")),
            )
    for pattern in _ROLE:
        match = pattern.fullmatch(normalized)
        if match:
            team = match.groupdict().get("team") or default_team
            if not team:
                raise SoftwareIncUIValidationError(
                    "role assignment requires an explicit target team"
                )
            return OfficeIntent(
                action=SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE,
                team_name=team,
                employee_name=match.group("employee"),
                role=SupportedEmployeeRole(match.group("role").title()),
            )
    raise SoftwareIncUIValidationError(
        "unsupported office request; use `set <team> working hours to <start>-<end>` or "
        "`assign <employee> as <role> for <team>`"
    )


def project_team_readiness(snapshot: GameSnapshot, team_name: str) -> TeamOfficeReadiness:
    team = _unique_named(_complete(snapshot, "teams"), "team", "name", team_name)
    offices = _complete(snapshot, "offices")
    infrastructure = _complete(snapshot, "infrastructure")
    rooms = tuple(
        _room(entity) for entity in offices.entities if entity.entity_type == "office_room"
    )
    assigned = tuple(room for room in rooms if _matches(team_name, room.assigned_teams))
    assigned_room_ids = {room.room_id for room in assigned}
    equipment = tuple(
        _equipment(entity)
        for entity in offices.entities
        if entity.entity_type == "office_equipment"
        and _text(entity, "room_id") in assigned_room_ids
    )
    current_capacity = sum(room.valid_workstations for room in assigned)
    required = _integer(team, "employee_count")
    missing = max(0, required - current_capacity)
    alternatives = tuple(
        room.room_id
        for room in rooms
        if team_name.casefold() not in {name.casefold() for name in room.assigned_teams}
        and not room.assigned_teams
        and room.available_workstations > 0
    )
    servers = tuple(
        _server(entity)
        for entity in infrastructure.entities
        if entity.entity_type == "server_group"
    )
    cash = _cash(snapshot)
    unknowns = [
        "Furniture utility draw is observed, but a complete monthly utility-cost projection "
        "is not verified.",
        "No universal source-control-server prerequisite is verified for teams in Software "
        "Inc. 1.8.41.",
    ]
    if any(room.major_problem or room.problem_count for room in assigned):
        unknowns.append(
            "At least one assigned room reports a problem; its localized problem text is "
            "not observed."
        )
    one_time_cost: Decimal | None = Decimal("0") if missing == 0 or alternatives else None
    recurring_cost: Decimal | None = Decimal("0") if missing == 0 or alternatives else None
    reserve = cash if missing == 0 or alternatives else None
    missing_resource = None if missing == 0 else f"{missing} valid assignable workstation(s)"
    if missing > 0 and alternatives:
        missing_resource = (
            f"assign {missing} existing valid workstation(s) from empty room(s) "
            + ", ".join(alternatives)
        )
    elif missing > 0:
        try:
            bundle = select_workstation_catalog(snapshot)
        except SoftwareIncUIValidationError as error:
            unknowns.insert(0, f"Exact workstation catalog bundle is unavailable: {error}.")
        else:
            parts: list[str] = []
            one_time_cost = Decimal("0")
            for _purpose, item in bundle:
                cash_quantity = max(0, missing - item.inventory_count)
                one_time_cost += item.one_time_cost * cash_quantity
                inventory = min(missing, item.inventory_count)
                detail = f"{missing}x {item.display_name}"
                if inventory:
                    detail += f" ({inventory} from inventory)"
                parts.append(detail)
            recurring_cost = Decimal("0")
            reserve = None if cash is None else cash - one_time_cost
            missing_resource = "; ".join(parts)
            unknowns.insert(
                0,
                "Final purchase remains contingent on a green live placement preview in the "
                "exact target room.",
            )
    return TeamOfficeReadiness(
        team_id=team.entity_id,
        team_name=_text(team, "name"),
        employee_count=required,
        work_start=_decimal(team, "work_start"),
        work_end=_decimal(team, "work_end"),
        current_capacity=current_capacity,
        required_capacity=required,
        missing_workstations=missing,
        assigned_rooms=assigned,
        assigned_equipment=equipment,
        cheaper_existing_capacity=alternatives,
        exact_missing_resource=missing_resource,
        expected_benefit=(
            "Observed valid workstation capacity meets the team's employee count."
            if missing == 0
            else "Provide one valid assignable workstation per currently observed team member."
        ),
        one_time_cost=one_time_cost,
        recurring_cost=recurring_cost,
        observed_cash=cash,
        cash_reserve_after_purchase=reserve,
        servers=servers,
        material_unknowns=tuple(unknowns),
    )


def require_unique_employee(
    snapshot: GameSnapshot, employee_name: str, team_name: str
) -> ObservedEntity:
    employees = _complete(snapshot, "employees")
    matches = [
        entity
        for entity in employees.entities
        if entity.entity_type == "employee"
        and _text(entity, "name").casefold() == employee_name.casefold()
        and _text(entity, "team").casefold() == team_name.casefold()
    ]
    if len(matches) != 1:
        detail = "does not exist on the requested team" if not matches else "is ambiguous"
        raise SoftwareIncUIValidationError(f"employee {employee_name!r} {detail}")
    return matches[0]


def verify_working_hours(before: GameSnapshot, after: GameSnapshot, intent: OfficeIntent) -> None:
    if intent.work_start is None or intent.work_end is None:
        raise SoftwareIncUIValidationError("working-hours verification requires exact bounds")
    left = _unique_named(_complete(before, "teams"), "team", "name", intent.team_name)
    right = _unique_named(_complete(after, "teams"), "team", "name", intent.team_name)
    if (
        _decimal(right, "work_start") != intent.work_start
        or _decimal(right, "work_end") != intent.work_end
    ):
        raise SoftwareIncUIVerificationError("exact team working hours were not observed")
    if _text(left, "name") != _text(right, "name") or _integer(left, "employee_count") != _integer(
        right, "employee_count"
    ):
        raise SoftwareIncUIVerificationError("team identity or membership changed unexpectedly")


def verify_employee_role(before: GameSnapshot, after: GameSnapshot, intent: OfficeIntent) -> None:
    if intent.employee_name is None or intent.role is None:
        raise SoftwareIncUIValidationError("role verification requires an employee and role")
    left = require_unique_employee(before, intent.employee_name, intent.team_name)
    right = require_unique_employee(after, intent.employee_name, intent.team_name)
    if intent.role.value.casefold() not in _text(right, "role").casefold():
        raise SoftwareIncUIVerificationError("requested employee role was not observed")
    for field in ("name", "team", "salary"):
        if left.values.get(field) != right.values.get(field):
            raise SoftwareIncUIVerificationError(f"employee {field} changed unexpectedly")


def _complete(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1 or matches[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise SoftwareIncUIValidationError(f"complete {name} observation is required")
    return matches[0]


def _unique_named(
    surface: ObservationSurface, entity_type: str, field: str, requested: str
) -> ObservedEntity:
    matches = [
        entity
        for entity in surface.entities
        if entity.entity_type == entity_type
        and _text(entity, field).casefold() == requested.casefold()
    ]
    if len(matches) != 1:
        detail = "does not exist" if not matches else "is ambiguous"
        raise SoftwareIncUIValidationError(f"{entity_type} {requested!r} {detail}")
    return matches[0]


def _room(entity: ObservedEntity) -> RoomReadiness:
    return RoomReadiness(
        room_id=entity.entity_id,
        floor=_integer(entity, "floor"),
        assigned_teams=tuple(
            sorted(filter(None, _text(entity, "assigned_teams", allow_empty=True).split("|")))
        ),
        assignable_workstations=_integer(entity, "assignable_workstations"),
        valid_workstations=_integer(entity, "valid_workstations"),
        available_workstations=_integer(entity, "available_workstations"),
        total_furniture=_integer(entity, "total_furniture"),
        major_problem=_boolean(entity, "major_problem"),
        problem_count=_integer(entity, "problem_count"),
        is_lit=_boolean(entity, "is_lit"),
        environment=_decimal(entity, "environment"),
        temperature=_decimal(entity, "temperature"),
        acoustics=_decimal(entity, "acoustics"),
    )


def _server(entity: ObservedEntity) -> ServerReadiness:
    return ServerReadiness(
        server_id=entity.entity_id,
        name=_text(entity, "name"),
        display_name=_text(entity, "display_name"),
        is_cloud=_boolean(entity, "is_cloud"),
        available=_decimal(entity, "available"),
        broken=_boolean(entity, "broken"),
        server_count=_integer(entity, "server_count"),
        item_count=_integer(entity, "item_count"),
        recurring_cost=_decimal(entity, "recurring_cost"),
        total_power=_decimal(entity, "total_power"),
    )


def _equipment(entity: ObservedEntity) -> EquipmentReadiness:
    return EquipmentReadiness(
        equipment_id=entity.entity_id,
        room_id=_text(entity, "room_id"),
        name=_text(entity, "name"),
        assignable=_boolean(entity, "assignable"),
        needs_chair=_boolean(entity, "needs_chair"),
        actions=tuple(filter(None, _text(entity, "actions", allow_empty=True).split("|"))),
        categories=tuple(filter(None, _text(entity, "category", allow_empty=True).split("|"))),
        function_category=_text(entity, "function_category", allow_empty=True),
        valid=_boolean(entity, "valid"),
        blocked=_boolean(entity, "blocked"),
        owner_employee_id=_text(entity, "owner_employee_id", allow_empty=True) or None,
        owner_employee_name=_text(entity, "owner_employee_name", allow_empty=True) or None,
        one_time_cost=_decimal(entity, "one_time_cost"),
        current_wattage=_decimal(entity, "current_wattage"),
        computer_power=_decimal(entity, "computer_power"),
        comfort=_decimal(entity, "comfort"),
        environment=_decimal(entity, "environment"),
    )


def _cash(snapshot: GameSnapshot) -> Decimal | None:
    try:
        surface = _complete(snapshot, "finances")
    except SoftwareIncUIValidationError:
        matches = [s for s in snapshot.surfaces if s.coverage.surface == "finances"]
        if len(matches) != 1:
            return None
        surface = matches[0]
    if len(surface.entities) != 1:
        return None
    value = surface.entities[0].values.get("cash")
    try:
        return Decimal(str(value)) if not isinstance(value, bool) and value is not None else None
    except InvalidOperation:
        return None


def _matches(name: str, values: tuple[str, ...]) -> bool:
    return name.casefold() in {value.casefold() for value in values}


def _text(entity: ObservedEntity, field: str, *, allow_empty: bool = False) -> str:
    value = entity.values.get(field)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed text")
    return value


def _integer(entity: ObservedEntity, field: str) -> int:
    value = entity.values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an observed integer")
    return value


def _boolean(entity: ObservedEntity, field: str) -> bool:
    value = entity.values.get(field)
    if not isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an observed boolean")
    return value


def _decimal(entity: ObservedEntity, field: str) -> Decimal:
    value = entity.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an observed number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise SoftwareIncUIValidationError(
            f"{entity.entity_id}.{field} is not a finite number"
        ) from error
    if not result.is_finite():
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not finite")
    return result


def _hour(value: str) -> Decimal:
    hour, separator, minute = value.partition(":")
    result = Decimal(hour)
    if separator:
        minute_value = int(minute)
        if minute_value < 0 or minute_value > 59:
            raise SoftwareIncUIValidationError("working-hours minutes must be between 00 and 59")
        result += Decimal(minute_value) / Decimal(60)
    return result


__all__ = [
    "EquipmentReadiness",
    "OfficeIntent",
    "OfficeOperationResult",
    "OfficePurchaseApproval",
    "RoomReadiness",
    "ServerReadiness",
    "SupportedEmployeeRole",
    "TeamOfficeReadiness",
    "parse_office_intent",
    "project_team_readiness",
    "require_unique_employee",
    "verify_employee_role",
    "verify_working_hours",
]
