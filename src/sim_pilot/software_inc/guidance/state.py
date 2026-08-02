"""Typed current-save projection for Software Inc. guidance."""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TeamSummary(StateModel):
    schema_version: Literal[1] = 1
    team_id: str
    name: str
    employee_count: int = Field(ge=0)
    work_start: Decimal | None = None
    work_end: Decimal | None = None


class EmployeeSummary(StateModel):
    schema_version: Literal[1] = 1
    employee_id: str
    name: str
    role: str
    team: str
    monthly_salary: Decimal = Field(ge=0)
    founder: bool | None = None


class SoftwareIncStateView(StateModel):
    schema_version: Literal[1] = 1
    snapshot_id: str = Field(pattern=r"^snapshot:[0-9a-f]{20}$")
    game_version: str
    adapter_version: str
    bridge_instance_id: str
    game_session_id: str
    save_identity: str | None = None
    bridge_sequence: int = Field(ge=1)
    paused: bool
    company_name: str | None = None
    cash: Decimal | None = None
    valuation: Decimal | None = None
    teams_complete: bool
    employees_complete: bool
    finances_partial: bool
    teams: tuple[TeamSummary, ...]
    employees: tuple[EmployeeSummary, ...]
    recurring_payroll: Decimal | None = Field(default=None, ge=0)
    warnings: tuple[str, ...] = ()


def project_state(snapshot: GameSnapshot) -> SoftwareIncStateView:
    surfaces = {surface.coverage.surface: surface for surface in snapshot.surfaces}
    company = surfaces.get("company")
    finances = surfaces.get("finances")
    teams_surface = surfaces.get("teams")
    employees_surface = surfaces.get("employees")

    company_name = _first_string(company, "name")
    cash = _first_decimal(finances, "cash")
    valuation = _first_decimal(finances, "valuation")
    teams_complete = _complete(teams_surface)
    employees_complete = _complete(employees_surface)
    warnings: list[str] = []

    teams: list[TeamSummary] = []
    if teams_complete and teams_surface is not None:
        for entity in teams_surface.entities:
            name = entity.values.get("name")
            count = entity.values.get("employee_count")
            if not isinstance(name, str) or not isinstance(count, int) or isinstance(count, bool):
                warnings.append(f"team {entity.entity_id} has incomplete identity or count")
                continue
            teams.append(
                TeamSummary(
                    team_id=entity.entity_id,
                    name=name,
                    employee_count=count,
                    work_start=_decimal(entity.values.get("work_start")),
                    work_end=_decimal(entity.values.get("work_end")),
                )
            )

    employees: list[EmployeeSummary] = []
    if employees_complete and employees_surface is not None:
        for entity in employees_surface.entities:
            values = entity.values
            name = values.get("name")
            role = values.get("role")
            team = values.get("team")
            salary = _decimal(values.get("salary"))
            founder = values.get("founder")
            if (
                not isinstance(name, str)
                or not isinstance(role, str)
                or not isinstance(team, str)
                or salary is None
            ):
                warnings.append(f"employee {entity.entity_id} has incomplete guidance fields")
                continue
            employees.append(
                EmployeeSummary(
                    employee_id=entity.entity_id,
                    name=name,
                    role=role,
                    team=team,
                    monthly_salary=salary,
                    founder=founder if isinstance(founder, bool) else None,
                )
            )

    payroll = (
        sum((employee.monthly_salary for employee in employees), start=Decimal("0"))
        if employees_complete
        and len(employees) == len(employees_surface.entities if employees_surface else ())
        else None
    )
    save_identity = snapshot.save_identity.value
    digest = hashlib.sha256(
        f"{snapshot.bridge_instance_id}|{snapshot.game_session_id}|"
        f"{save_identity}|{snapshot.bridge_sequence}".encode()
    ).hexdigest()[:20]
    paused = snapshot.game_state.get("force_pause") is True or snapshot.game_state.get(
        "simulation_speed"
    ) in {"0", "0.0"}
    return SoftwareIncStateView(
        snapshot_id=f"snapshot:{digest}",
        game_version=snapshot.game_version,
        adapter_version=snapshot.adapter_version,
        bridge_instance_id=snapshot.bridge_instance_id,
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        bridge_sequence=snapshot.bridge_sequence,
        paused=paused,
        company_name=company_name,
        cash=cash,
        valuation=valuation,
        teams_complete=teams_complete,
        employees_complete=employees_complete,
        finances_partial=(
            finances is not None and finances.coverage.status is CoverageStatus.OBSERVED_PARTIAL
        ),
        teams=tuple(sorted(teams, key=lambda item: (item.name.casefold(), item.team_id))),
        employees=tuple(
            sorted(employees, key=lambda item: (item.name.casefold(), item.employee_id))
        ),
        recurring_payroll=payroll,
        warnings=tuple(warnings),
    )


def _complete(surface: ObservationSurface | None) -> bool:
    return surface is not None and surface.coverage.status is CoverageStatus.OBSERVED_COMPLETE


def _first_string(surface: ObservationSurface | None, field: str) -> str | None:
    if surface is None or len(surface.entities) != 1:
        return None
    value = surface.entities[0].values.get(field)
    return value if isinstance(value, str) else None


def _first_decimal(surface: ObservationSurface | None, field: str) -> Decimal | None:
    if surface is None or len(surface.entities) != 1:
        return None
    return _decimal(surface.entities[0].values.get(field))


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


__all__ = ["EmployeeSummary", "SoftwareIncStateView", "TeamSummary", "project_state"]
