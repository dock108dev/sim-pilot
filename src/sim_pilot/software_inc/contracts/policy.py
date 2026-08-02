"""Deterministic recommendation and suitability policy for the first contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import (
    ContractCandidate,
    ContractObservation,
    ContractRecommendation,
    TeamContractAssessment,
)
from .projection import active_contract_work, available_contracts, require_complete_surface

_RECOMMENDATION_TTL = timedelta(minutes=3)


def recommend_contracts(
    snapshot: GameSnapshot,
    *,
    team_name: str,
    minimum_reward: Decimal,
    minimum_cash_reserve: Decimal = Decimal("0"),
    now: datetime | None = None,
) -> ContractRecommendation:
    """Return one recommendation and at most two alternatives from complete observations."""
    if minimum_reward < 0 or minimum_cash_reserve < 0:
        raise SoftwareIncUIValidationError("reward and cash reserve constraints cannot be negative")
    contracts = available_contracts(snapshot)
    candidates = tuple(
        assess_contract(
            snapshot,
            contract,
            team_name=team_name,
            minimum_reward=minimum_reward,
            minimum_cash_reserve=minimum_cash_reserve,
        )
        for contract in contracts
    )
    eligible = sorted(
        (item for item in candidates if item.eligible),
        key=lambda item: (
            -item.contract.reward,
            -item.team.deadline_buffer_days,
            item.contract.difficulty,
            item.contract.contract_id,
        ),
    )
    rejected = tuple(item for item in candidates if not item.eligible)
    rejection_reasons = tuple(
        sorted({reason for candidate in rejected for reason in candidate.reasons})
    )
    created = now or datetime.now(UTC)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "adapter": snapshot.adapter_version,
        "game_session_id": snapshot.game_session_id,
        "save_identity": save_identity,
        "sequence": snapshot.bridge_sequence,
        "team": team_name,
        "minimum_reward": str(minimum_reward),
        "minimum_cash_reserve": str(minimum_cash_reserve),
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return ContractRecommendation(
        recommendation_id=f"contract-recommendation:{fingerprint[:24]}",
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        source_bridge_sequence=snapshot.bridge_sequence,
        capability_fingerprint=fingerprint,
        recommended=eligible[0] if eligible else None,
        alternatives=tuple(eligible[1:3]),
        rejected_count=len(rejected),
        rejection_reasons=rejection_reasons,
        material_unknowns=(
            "Before acceptance, Software Inc. exposes a relative completion window rather than "
            "an absolute deadline. The estimate compares that generated window with the "
            "observed employee-month workload and current days-per-month setting; it does not "
            "predict interruptions or employee effectiveness.",
            "Detailed future operating cash flow is unavailable, so the policy reserves "
            "the full observed contract penalty.",
        ),
        created_at=created,
        expires_at=created + _RECOMMENDATION_TTL,
    )


def assess_contract(
    snapshot: GameSnapshot,
    contract: ContractObservation,
    *,
    team_name: str,
    minimum_reward: Decimal,
    minimum_cash_reserve: Decimal,
) -> ContractCandidate:
    team = _unique_named_team(snapshot, team_name)
    employees = _team_employees(snapshot, team_name)
    required_roles = ("Designer",)
    if contract.art_ratio < 1:
        required_roles += ("Programmer",)
    if contract.art_ratio > 0:
        required_roles += ("Artist",)
    observed_roles = tuple(
        sorted({role for employee in employees for role in _observed_roles(employee)})
    )
    missing_roles = tuple(
        role
        for role in required_roles
        if role.casefold() not in {item.casefold() for item in observed_roles}
    )
    active = tuple(
        item.contract_name
        for item in active_contract_work(snapshot)
        if team_name.casefold() in {team.casefold() for team in item.assigned_teams}
        and not item.done
    )
    employee_count = _integer(team, "employee_count")
    capacity = _workspace_capacity(snapshot, team_name)
    days_per_month = _days_per_month(snapshot)
    conservative_required_days = (contract.development_time * days_per_month).to_integral_value(
        rounding=ROUND_CEILING
    )
    buffer = contract.days_remaining - conservative_required_days
    team_reasons: list[str] = []
    if employee_count < 1:
        team_reasons.append("the team has no observed employees")
    if missing_roles:
        team_reasons.append("missing required observed roles: " + ", ".join(missing_roles))
    if active:
        team_reasons.append(
            "higher-priority existing work would be displaced: " + ", ".join(active)
        )
    if capacity is None:
        team_reasons.append("workspace capacity is not completely attributable to the team")
    elif capacity < employee_count:
        team_reasons.append(
            f"workspace capacity {capacity} is below employee count {employee_count}"
        )
    if buffer < 0:
        team_reasons.append(
            f"completion window has {contract.days_remaining} in-game days but the conservative "
            f"budget is {conservative_required_days} days"
        )
    assessment = TeamContractAssessment(
        team_id=team.entity_id,
        team_name=_text(team, "name"),
        employee_count=employee_count,
        required_roles=required_roles,
        observed_roles=observed_roles,
        missing_roles=missing_roles,
        active_work_items=active,
        current_workspace_capacity=capacity,
        required_workspace_capacity=employee_count,
        conservative_required_days=conservative_required_days,
        deadline_buffer_days=buffer,
        suitable=not team_reasons,
        reasons=tuple(team_reasons),
    )
    cash = _cash(snapshot)
    worst_case = cash - contract.penalty
    reasons = list(team_reasons)
    if contract.reward < minimum_reward:
        reasons.append(
            f"reward ${contract.reward:,.2f} is below the requested ${minimum_reward:,.2f} minimum"
        )
    if worst_case < minimum_cash_reserve:
        reasons.append(
            f"reserving the full ${contract.penalty:,.2f} penalty leaves "
            f"${worst_case:,.2f}, below the ${minimum_cash_reserve:,.2f} reserve"
        )
    if contract.days_remaining <= 0:
        reasons.append("the observed relative completion window is not positive")
    return ContractCandidate(
        contract=contract,
        team=assessment,
        observed_cash=cash,
        worst_case_cash_after_penalty=worst_case,
        minimum_reward=minimum_reward,
        minimum_cash_reserve=minimum_cash_reserve,
        eligible=not reasons,
        reasons=tuple(reasons),
    )


def _unique_named_team(snapshot: GameSnapshot, requested: str) -> ObservedEntity:
    surface = require_complete_surface(snapshot, "teams")
    wanted = " ".join(requested.casefold().split())
    matches = [
        entity
        for entity in surface.entities
        if entity.entity_type == "team"
        and " ".join(_text(entity, "name").casefold().split()) == wanted
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"team {requested!r} did not resolve exactly once in complete observations"
        )
    return matches[0]


def _team_employees(snapshot: GameSnapshot, team_name: str) -> tuple[ObservedEntity, ...]:
    surface = require_complete_surface(snapshot, "employees")
    return tuple(
        entity
        for entity in surface.entities
        if entity.entity_type == "employee"
        and _text(entity, "team", empty=True).casefold() == team_name.casefold()
        and entity.values.get("dismissed") is False
    )


def _observed_roles(employee: ObservedEntity) -> tuple[str, ...]:
    role = _text(employee, "role")
    if "any role" in role.casefold():
        skill_fields = (
            ("Designer", "skill_designer"),
            ("Programmer", "skill_programmer"),
            ("Artist", "skill_artist"),
            ("Lead", "skill_lead"),
            ("Service", "skill_service"),
        )
        observed = tuple(
            name for name, field in skill_fields if _nonnegative_number(employee, field) > 0
        )
        return observed or (role,)
    matches = tuple(
        name
        for name in ("Lead", "Programmer", "Designer", "Artist", "Service")
        if name.casefold() in role.casefold()
    )
    return matches or (role,)


def _nonnegative_number(entity: ObservedEntity, field: str) -> Decimal:
    value = entity.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed numeric")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is invalid")
    return result


def _workspace_capacity(snapshot: GameSnapshot, team_name: str) -> int | None:
    surface = require_complete_surface(snapshot, "offices")
    capacity = 0
    matched = False
    for entity in surface.entities:
        if entity.entity_type != "office_room":
            continue
        teams = _text(entity, "assigned_teams", empty=True).split("|")
        if team_name.casefold() not in {team.casefold() for team in teams if team}:
            continue
        matched = True
        capacity += _integer(entity, "valid_workstations")
    return capacity if matched else None


def _days_per_month(snapshot: GameSnapshot) -> int:
    value = snapshot.game_state.get("days_per_month")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SoftwareIncUIValidationError("days_per_month is not observed from the current save")
    return value


def _cash(snapshot: GameSnapshot) -> Decimal:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == "finances"]
    if len(matches) != 1 or matches[0].coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        raise SoftwareIncUIValidationError("current finances are not observed")
    surface = matches[0]
    if len(surface.entities) != 1:
        raise SoftwareIncUIValidationError("current cash did not resolve exactly once")
    value = surface.entities[0].values.get("cash")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIValidationError("current cash is not observed")
    return Decimal(str(value))


def _text(entity: ObservedEntity, field: str, *, empty: bool = False) -> str:
    value = entity.values.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed text")
    return value


def _integer(entity: ObservedEntity, field: str) -> int:
    value = entity.values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an integer")
    return value


__all__ = ["assess_contract", "recommend_contracts"]
