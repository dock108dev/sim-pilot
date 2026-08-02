"""Deterministic teams-and-hiring intent, policy, approval, and semantic verification."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from sim_pilot.domain import Action
from sim_pilot.game_bridge import (
    CoverageStatus,
    GameSnapshot,
    ObservationSurface,
    ObservedEntity,
)
from sim_pilot.game_bridge.models import JsonValue
from sim_pilot.software_inc.errors import (
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import (
    ApplicantObservation,
    HiringSearchObservation,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    StaffingApproval,
    StaffingApprovalStatus,
    StaffingIntent,
    StaffingPlan,
)

_CREATE_PATTERNS = (
    re.compile(r"^create\s+(?:a\s+)?team\s+named\s+(?P<name>.+?)[.]?$", re.IGNORECASE),
    re.compile(r"^make\s+(?:a\s+)?new\s+team\s+called\s+(?P<name>.+?)[.]?$", re.IGNORECASE),
)
_HIRE_PATTERNS = (
    re.compile(
        r"^hire\s+(?:one|a)\s+programmer\s+(?:for|into)\s+(?P<team>.+?)\s+"
        r"for\s+no\s+more\s+than\s+\$?(?P<amount>[\d,]+(?:\.\d{1,2})?)\s+per\s+month$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^hire\s+(?:one|a)\s+programmer\s+(?:for|into)\s+(?P<team>.+?)\s+"
        r"with\s+(?:a\s+)?monthly\s+salary\s+cap\s+of\s+"
        r"\$?(?P<amount>[\d,]+(?:\.\d{1,2})?)$",
        re.IGNORECASE,
    ),
)
_OBSERVE_PATTERNS = (
    re.compile(
        r"^(?:list|observe|show)\s+(?:the\s+)?programmer\s+applicants\s+for\s+"
        r"(?P<team>.+?)\s+(?:under|at\s+or\s+below|for\s+no\s+more\s+than)\s+"
        r"\$?(?P<amount>[\d,]+(?:\.\d{1,2})?)\s+per\s+month$",
        re.IGNORECASE,
    ),
)
_PLAN_TTL = timedelta(minutes=2)
_FORBIDDEN_SURFACES = ("company", "offices", "products", "work_items")


def normalize_team_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def parse_staffing_intent(instruction: str) -> StaffingIntent:
    normalized = " ".join(instruction.strip().split())
    for pattern in _CREATE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return StaffingIntent(
                action=SoftwareIncUIAction.CREATE_TEAM,
                team_name=match.group("name"),
            )
    for pattern in _HIRE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return StaffingIntent(
                action=SoftwareIncUIAction.HIRE_EMPLOYEE,
                team_name=match.group("team"),
                role="Programmer",
                maximum_monthly_salary=_money(match.group("amount")),
            )
    for pattern in _OBSERVE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return StaffingIntent(
                action=SoftwareIncUIAction.OBSERVE_APPLICANTS,
                team_name=match.group("team"),
                role="Programmer",
                maximum_monthly_salary=_money(match.group("amount")),
            )
    if normalized.casefold().startswith("hire"):
        raise SoftwareIncUIValidationError(
            "hiring requires exactly one programmer, one target team, and an explicit USD "
            "monthly salary cap"
        )
    if "team" in normalized.casefold():
        raise SoftwareIncUIValidationError("team creation requires `create a team named <name>`")
    raise SoftwareIncUIValidationError("unsupported Software Inc. staffing request")


def team_entities(snapshot: GameSnapshot) -> tuple[ObservedEntity, ...]:
    return _complete_surface(snapshot, "teams").entities


def employee_entities(snapshot: GameSnapshot) -> tuple[ObservedEntity, ...]:
    return _complete_surface(snapshot, "employees").entities


def applicant_observations(snapshot: GameSnapshot) -> tuple[ApplicantObservation, ...]:
    surface = _complete_surface(snapshot, "applicants")
    applicants: list[ApplicantObservation] = []
    seen_ids: set[str] = set()
    seen_indexes: set[int] = set()
    for entity in surface.entities:
        if entity.entity_type != "applicant":
            continue
        values = entity.values
        try:
            display_index = values["display_index"]
            salary = values["salary"]
            if (
                not isinstance(display_index, int)
                or isinstance(display_index, bool)
                or not isinstance(salary, (int, float))
                or isinstance(salary, bool)
            ):
                raise TypeError
            salary_period = _text(values, "salary_period")
            if salary_period != "monthly":
                raise ValueError
            applicant = ApplicantObservation(
                applicant_id=entity.entity_id,
                name=_text(values, "name"),
                role=_text(values, "role"),
                salary=Decimal(str(salary)),
                salary_period="monthly",
                wage_bracket=_text(values, "wage_bracket"),
                display_index=display_index,
                selected_team=_text(values, "selected_team", allow_empty=True),
                available=_boolean(values, "available"),
                source_bridge_sequence=snapshot.bridge_sequence,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise SoftwareIncUIValidationError(
                f"applicant {entity.entity_id!r} has incomplete or invalid observed fields"
            ) from error
        if applicant.applicant_id in seen_ids or applicant.display_index in seen_indexes:
            raise SoftwareIncUIValidationError(
                "applicant coverage contains duplicate identity or display index"
            )
        seen_ids.add(applicant.applicant_id)
        seen_indexes.add(applicant.display_index)
        applicants.append(applicant)
    return tuple(sorted(applicants, key=lambda item: item.display_index))


def hiring_search_observation(snapshot: GameSnapshot) -> HiringSearchObservation:
    surface = _complete_surface(snapshot, "staffing_ui")
    states = [
        entity
        for entity in surface.entities
        if entity.entity_type == "staffing_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        raise SoftwareIncUIValidationError("staffing UI state did not resolve exactly once")
    values = states[0].values
    if _text(values, "scene") != "hiring_setup":
        raise SoftwareIncUIValidationError("paid applicant search is not visibly configured")
    role = _text(values, "role")
    wage_bracket = _text(values, "wage_bracket")
    pool_text = _text(values, "pool_text")
    cost_text = _text(values, "search_cost_text")
    matches = re.findall(r"(?<![\d.])[\d][\d,]*(?:\.\d{1,2})?", cost_text)
    if not matches:
        raise SoftwareIncUIValidationError("visible applicant-search cost is not a USD amount")
    return HiringSearchObservation(
        role=role,
        wage_bracket=wage_bracket,
        one_time_cost=_money(matches[-1]),
        pool_text=pool_text,
        source_bridge_sequence=snapshot.bridge_sequence,
    )


def require_unique_team(snapshot: GameSnapshot, requested: str) -> ObservedEntity:
    wanted = normalize_team_name(requested)
    matches = [
        entity
        for entity in team_entities(snapshot)
        if normalize_team_name(_text(entity.values, "name")) == wanted
    ]
    if not matches:
        raise SoftwareIncUIValidationError(f"team {requested!r} does not exist")
    if len(matches) > 1:
        raise SoftwareIncUIValidationError(f"team {requested!r} is ambiguous")
    return matches[0]


def require_team_absent(snapshot: GameSnapshot, requested: str) -> None:
    wanted = normalize_team_name(requested)
    matches = [
        entity
        for entity in team_entities(snapshot)
        if normalize_team_name(_text(entity.values, "name")) == wanted
    ]
    if matches:
        raise SoftwareIncUIValidationError(
            f"team {requested!r} already exists; duplicate creation rejected"
        )


def select_applicant(
    snapshot: GameSnapshot,
    *,
    team_name: str,
    role: str,
    maximum_monthly_salary: Decimal,
) -> ApplicantObservation:
    require_unique_team(snapshot, team_name)
    employed_ids = {entity.entity_id for entity in employee_entities(snapshot)}
    eligible = [
        applicant
        for applicant in applicant_observations(snapshot)
        if applicant.available
        and applicant.role.casefold() == role.casefold()
        and applicant.salary <= maximum_monthly_salary
        and applicant.applicant_id not in employed_ids
        and (
            not applicant.selected_team
            or normalize_team_name(applicant.selected_team) == normalize_team_name(team_name)
        )
    ]
    if not eligible:
        raise SoftwareIncUIValidationError(
            f"no available {role} applicant was observed at or below "
            f"${maximum_monthly_salary:,.2f} per month"
        )
    return min(eligible, key=lambda applicant: (applicant.salary, applicant.applicant_id))


def build_staffing_plan(
    intent: StaffingIntent,
    observation: SoftwareIncUIObservation,
    *,
    applicant: ApplicantObservation | None = None,
    now: datetime | None = None,
) -> StaffingPlan:
    current = now or datetime.now(UTC)
    snapshot = observation.semantic_after
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if intent.action is SoftwareIncUIAction.CREATE_TEAM:
        require_team_absent(snapshot, intent.team_name)
        expected = (f"teams.add:{normalize_team_name(intent.team_name)}",)
        applicant = None
        search = None
        maximum = None
        one_time_cost = Decimal("0")
        monthly_cost = Decimal("0")
    elif intent.action is SoftwareIncUIAction.OBSERVE_APPLICANTS:
        if intent.role is None or intent.maximum_monthly_salary is None:
            raise SoftwareIncUIValidationError("applicant-search intent lacks role or salary limit")
        require_unique_team(snapshot, intent.team_name)
        search = hiring_search_observation(snapshot)
        if search.role.casefold() != intent.role.casefold():
            raise SoftwareIncUIValidationError("visible applicant-search role is not Programmer")
        expected = (
            f"finances.cash:-{search.one_time_cost}",
            "applicants.replace:visible_pool",
        )
        applicant = None
        maximum = intent.maximum_monthly_salary
        one_time_cost = search.one_time_cost
        monthly_cost = Decimal("0")
    elif intent.action is SoftwareIncUIAction.HIRE_EMPLOYEE:
        if intent.role is None or intent.maximum_monthly_salary is None:
            raise SoftwareIncUIValidationError("hire intent lacks role or salary limit")
        selected = applicant or select_applicant(
            snapshot,
            team_name=intent.team_name,
            role=intent.role,
            maximum_monthly_salary=intent.maximum_monthly_salary,
        )
        if selected.salary > intent.maximum_monthly_salary:
            raise SoftwareIncUIValidationError("selected applicant exceeds the salary limit")
        expected = (
            f"employees.add:{selected.applicant_id}",
            f"employees.team:{selected.applicant_id}:{normalize_team_name(intent.team_name)}",
            f"employees.salary:{selected.applicant_id}:{selected.salary}",
        )
        applicant = selected
        search = None
        maximum = intent.maximum_monthly_salary
        one_time_cost = Decimal("0")
        monthly_cost = selected.salary
    else:
        raise SoftwareIncUIValidationError("applicant observation does not create a mutation plan")
    material = {
        "action": intent.action.value,
        "applicant": None if applicant is None else applicant.model_dump(mode="json"),
        "game_session_id": snapshot.game_session_id,
        "maximum_monthly_salary": None if maximum is None else str(maximum),
        "search": None if search is None else search.model_dump(mode="json"),
        "save_identity": save_identity,
        "source_frame_id": observation.frame.frame_id,
        "source_projection_id": observation.projection_id,
        "team_name": intent.team_name,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return StaffingPlan(
        plan_id=uuid5(NAMESPACE_URL, f"sim-pilot:software-inc:staffing-plan:{fingerprint}"),
        action=intent.action,
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        team_name=intent.team_name,
        normalized_team_name=normalize_team_name(intent.team_name),
        applicant=applicant,
        search=search,
        maximum_monthly_salary=maximum,
        expected_one_time_cost=one_time_cost,
        expected_monthly_cost=monthly_cost,
        expected_differences=expected,
        forbidden_differences=tuple(f"{surface}.*" for surface in _FORBIDDEN_SURFACES),
        source_frame_id=observation.frame.frame_id,
        source_projection_id=observation.projection_id,
        created_at=current,
        expires_at=current + _PLAN_TTL,
        fingerprint=fingerprint,
    )


def pending_approval(plan: StaffingPlan) -> StaffingApproval:
    action = Action(
        type=plan.action.value,
        parameters={
            "plan_fingerprint": plan.fingerprint,
            "team_name": plan.team_name,
            "applicant_id": None if plan.applicant is None else plan.applicant.applicant_id,
            "one_time_cost": str(plan.expected_one_time_cost),
            "monthly_salary": str(plan.expected_monthly_cost),
        },
        expected_effect="; ".join(plan.expected_differences),
        estimated_cost=max(plan.expected_one_time_cost, plan.expected_monthly_cost),
    )
    return StaffingApproval(
        id=uuid5(NAMESPACE_URL, f"sim-pilot:approval:{plan.fingerprint}"),
        task_id=uuid5(NAMESPACE_URL, f"sim-pilot:staffing-task:{plan.fingerprint}"),
        action=action,
        created_at=plan.created_at,
        plan_fingerprint=plan.fingerprint,
    )


def resolve_approval(
    approval: StaffingApproval,
    *,
    approved: bool,
    now: datetime | None = None,
) -> StaffingApproval:
    return approval.model_copy(
        update={
            "status": (
                StaffingApprovalStatus.APPROVED if approved else StaffingApprovalStatus.DENIED
            ),
            "resolved_at": now or datetime.now(UTC),
        }
    )


def require_valid_approval(
    plan: StaffingPlan,
    approval: StaffingApproval,
    observation: SoftwareIncUIObservation,
    *,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(UTC)
    if approval.status is not StaffingApprovalStatus.APPROVED:
        raise SoftwareIncUIValidationError("exact staffing approval was not granted")
    if approval.plan_fingerprint != plan.fingerprint:
        raise SoftwareIncUIValidationError("approval belongs to a different staffing plan")
    if plan.expires_at <= current:
        raise SoftwareIncUIValidationError("staffing approval expired before commitment")
    snapshot = observation.semantic_after
    if snapshot.game_session_id != plan.game_session_id:
        raise SoftwareIncUIValidationError("game session changed after staffing approval")
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if save_identity != plan.save_identity:
        raise SoftwareIncUIValidationError("save identity changed after staffing approval")
    if plan.action is SoftwareIncUIAction.CREATE_TEAM:
        require_team_absent(snapshot, plan.team_name)
    elif plan.action is SoftwareIncUIAction.OBSERVE_APPLICANTS:
        current_search = hiring_search_observation(snapshot)
        if current_search != plan.search:
            raise SoftwareIncUIValidationError(
                "applicant-search role, bracket, pool, or cost changed after approval"
            )
    else:
        assert plan.applicant is not None and plan.maximum_monthly_salary is not None
        current_applicant = select_applicant(
            snapshot,
            team_name=plan.team_name,
            role=plan.applicant.role,
            maximum_monthly_salary=plan.maximum_monthly_salary,
        )
        if current_applicant != plan.applicant:
            raise SoftwareIncUIValidationError(
                "applicant identity, salary, order, or availability changed after approval"
            )


def verify_team_created(
    before: GameSnapshot,
    after: GameSnapshot,
    *,
    team_name: str,
) -> ObservedEntity:
    _require_snapshot_continuity(before, after)
    before_teams = {entity.entity_id: entity for entity in team_entities(before)}
    after_teams = {entity.entity_id: entity for entity in team_entities(after)}
    added = [entity for identity, entity in after_teams.items() if identity not in before_teams]
    if len(added) != 1:
        raise SoftwareIncUIVerificationError("team creation did not add exactly one team")
    created = added[0]
    if normalize_team_name(_text(created.values, "name")) != normalize_team_name(team_name):
        raise SoftwareIncUIVerificationError("created team name does not match the approved name")
    if employee_entities(before) != employee_entities(after):
        raise SoftwareIncUIVerificationError("team creation unexpectedly changed employees")
    _require_surfaces_unchanged(before, after, _FORBIDDEN_SURFACES)
    return created


def verify_employee_hired(
    before: GameSnapshot,
    after: GameSnapshot,
    *,
    plan: StaffingPlan,
) -> ObservedEntity:
    _require_snapshot_continuity(before, after)
    if plan.applicant is None or plan.maximum_monthly_salary is None:
        raise SoftwareIncUIVerificationError("hire verification requires an applicant plan")
    before_employees = {entity.entity_id: entity for entity in employee_entities(before)}
    after_employees = {entity.entity_id: entity for entity in employee_entities(after)}
    added = [
        entity for identity, entity in after_employees.items() if identity not in before_employees
    ]
    if len(added) != 1:
        raise SoftwareIncUIVerificationError("hiring did not add exactly one employee")
    hired = added[0]
    if hired.entity_id != plan.applicant.applicant_id:
        raise SoftwareIncUIVerificationError("hired employee does not match approved applicant")
    if _text(hired.values, "role").casefold() != plan.applicant.role.casefold():
        raise SoftwareIncUIVerificationError("hired employee role is not the approved role")
    if normalize_team_name(_text(hired.values, "team")) != plan.normalized_team_name:
        raise SoftwareIncUIVerificationError("hired employee is not assigned to the approved team")
    salary_value = hired.values.get("salary")
    if (
        not isinstance(salary_value, (int, float))
        or isinstance(salary_value, bool)
        or Decimal(str(salary_value)) != plan.applicant.salary
        or Decimal(str(salary_value)) > plan.maximum_monthly_salary
    ):
        raise SoftwareIncUIVerificationError("hired employee salary violates the approved plan")
    if len(team_entities(before)) != len(team_entities(after)):
        raise SoftwareIncUIVerificationError("hiring unexpectedly changed team count")
    before_team = require_unique_team(before, plan.team_name)
    after_team = require_unique_team(after, plan.team_name)
    before_count = before_team.values.get("employee_count")
    after_count = after_team.values.get("employee_count")
    if (
        not isinstance(before_count, int)
        or isinstance(before_count, bool)
        or not isinstance(after_count, int)
        or isinstance(after_count, bool)
        or after_count != before_count + 1
    ):
        raise SoftwareIncUIVerificationError(
            "target team recurring employee count did not increase by one"
        )
    before_payroll = _payroll(before_employees.values())
    after_payroll = _payroll(after_employees.values())
    if after_payroll - before_payroll != plan.applicant.salary:
        raise SoftwareIncUIVerificationError(
            "observed recurring payroll increase does not equal the approved salary"
        )
    _require_surfaces_unchanged(before, after, _FORBIDDEN_SURFACES)
    return hired


def verify_applicant_search(
    before: GameSnapshot,
    after: GameSnapshot,
    *,
    plan: StaffingPlan,
) -> tuple[ApplicantObservation, ...]:
    _require_snapshot_continuity(before, after)
    if (
        plan.action is not SoftwareIncUIAction.OBSERVE_APPLICANTS
        or plan.search is None
        or plan.maximum_monthly_salary is None
    ):
        raise SoftwareIncUIVerificationError("applicant-search verification requires a search plan")
    if team_entities(before) != team_entities(after):
        raise SoftwareIncUIVerificationError("applicant search unexpectedly changed teams")
    if employee_entities(before) != employee_entities(after):
        raise SoftwareIncUIVerificationError("applicant search unexpectedly changed employees")
    cash_delta = _cash(before) - _cash(after)
    if cash_delta != plan.expected_one_time_cost:
        raise SoftwareIncUIVerificationError(
            "applicant-search cash charge does not equal the approved one-time cost"
        )
    applicants = applicant_observations(after)
    if not applicants:
        raise SoftwareIncUIVerificationError("paid applicant search returned no visible applicants")
    _require_surfaces_unchanged(before, after, ("company", "offices", "products", "work_items"))
    return applicants


def _money(value: str) -> Decimal:
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation as error:
        raise SoftwareIncUIValidationError("salary cap must be a valid USD amount") from error
    if result <= 0:
        raise SoftwareIncUIValidationError("salary cap must be positive")
    return result.quantize(Decimal("0.01"))


def _complete_surface(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1 or matches[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        detail = "missing" if not matches else matches[0].coverage.status.value
        raise SoftwareIncUIValidationError(
            f"{name} coverage must be observed_complete; found {detail}"
        )
    return matches[0]


def _cash(snapshot: GameSnapshot) -> Decimal:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == "finances"]
    if len(matches) != 1 or matches[0].coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        raise SoftwareIncUIVerificationError("finance cash coverage is unavailable")
    entities = [
        entity for entity in matches[0].entities if entity.entity_type == "company_finances"
    ]
    if len(entities) != 1:
        raise SoftwareIncUIVerificationError("company finance entity did not resolve exactly once")
    cash = entities[0].values.get("cash")
    if not isinstance(cash, (int, float)) or isinstance(cash, bool):
        raise SoftwareIncUIVerificationError("company cash is not an observed numeric value")
    return Decimal(str(cash)).quantize(Decimal("0.01"))


def _text(values: Mapping[str, JsonValue], key: str, *, allow_empty: bool = False) -> str:
    value = values.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"{key} is not an observed string")
    return value


def _boolean(values: Mapping[str, JsonValue], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{key} is not an observed boolean")
    return value


def _require_snapshot_continuity(before: GameSnapshot, after: GameSnapshot) -> None:
    if (
        before.bridge_instance_id != after.bridge_instance_id
        or before.game_session_id != after.game_session_id
        or before.save_identity != after.save_identity
        or after.bridge_sequence <= before.bridge_sequence
    ):
        raise SoftwareIncUIVerificationError(
            "bridge, session, save, or sequence changed during staffing verification"
        )


def _require_surfaces_unchanged(
    before: GameSnapshot,
    after: GameSnapshot,
    names: tuple[str, ...],
) -> None:
    for name in names:
        if _surface_payload(before, name) != _surface_payload(after, name):
            raise SoftwareIncUIVerificationError(
                f"unexpected {name} semantic mutation during staffing action"
            )


def _surface_payload(snapshot: GameSnapshot, name: str) -> dict[str, object]:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1:
        raise SoftwareIncUIVerificationError(f"required verification surface {name} is missing")
    return matches[0].model_dump(mode="json")


def _payroll(employees: Iterable[ObservedEntity]) -> Decimal:
    total = Decimal("0")
    for entity in employees:
        salary = entity.values.get("salary")
        if not isinstance(salary, (int, float)) or isinstance(salary, bool):
            raise SoftwareIncUIVerificationError("employee salary coverage is incomplete")
        total += Decimal(str(salary))
    return total


__all__ = [
    "applicant_observations",
    "build_staffing_plan",
    "employee_entities",
    "hiring_search_observation",
    "normalize_team_name",
    "parse_staffing_intent",
    "pending_approval",
    "require_team_absent",
    "require_unique_team",
    "require_valid_approval",
    "resolve_approval",
    "select_applicant",
    "team_entities",
    "verify_employee_hired",
    "verify_applicant_search",
    "verify_team_created",
]
