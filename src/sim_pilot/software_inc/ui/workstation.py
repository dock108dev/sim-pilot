"""Exact, approval-gated workstation planning for Software Inc. 1.8.41."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import (
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import SoftwareIncUIAction, SoftwareIncUIObservation

_PLAN_TTL = timedelta(minutes=5)
_MONEY = Decimal("0.01")


class WorkstationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class WorkstationIntent(WorkstationModel):
    schema_version: Literal[1] = 1
    action: Literal[SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION] = (
        SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION
    )
    team_name: str = Field(min_length=1, max_length=64)
    quantity: Literal[1] = 1
    minimum_cash_reserve: Decimal = Field(default=Decimal("0"), ge=0)


class FurnitureCatalogItem(WorkstationModel):
    item_id: str
    display_name: str
    prefab_name: str
    furniture_type: str
    search_title: str
    one_time_cost: Decimal = Field(gt=0)
    wattage: Decimal = Field(ge=0)
    computer_power: Decimal = Field(ge=0)
    inventory_count: int = Field(ge=0)
    can_assign: bool
    needs_chair: bool
    is_snapping: bool
    snaps_to: tuple[str, ...]
    snap_points: tuple[str, ...]
    categories: tuple[str, ...]
    function_category: str


class WorkstationLineItem(WorkstationModel):
    sequence: int = Field(ge=1, le=8)
    purpose: Literal["work_surface", "computer", "chair", "trashcan"]
    catalog_item: FurnitureCatalogItem
    quantity: Literal[1] = 1
    total_price: Decimal = Field(gt=0)
    expected_cash_charge: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def exact_total(self) -> WorkstationLineItem:
        if self.total_price != self.catalog_item.one_time_cost:
            raise ValueError("line total must exactly equal the current catalog price")
        expected = Decimal("0") if self.catalog_item.inventory_count > 0 else self.total_price
        if self.expected_cash_charge != expected:
            raise ValueError("cash charge must account for currently observed inventory")
        return self


class WorkstationReusedComponent(WorkstationModel):
    purpose: Literal["work_surface", "computer", "chair", "trashcan"]
    equipment_id: str
    prefab_name: str
    display_name: str


class WorkstationPlan(WorkstationModel):
    schema_version: Literal[1] = 1
    plan_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    game_session_id: str
    save_identity: str
    team_id: str
    team_name: str
    room_id: str
    assign_room_to_team: bool
    previous_room_teams: tuple[str, ...]
    initial_valid_workstations: int = Field(ge=0)
    expected_valid_workstations: int = Field(ge=1)
    expected_room_problem_cleared: bool = False
    reused_components: tuple[WorkstationReusedComponent, ...] = ()
    line_items: tuple[WorkstationLineItem, ...]
    total_one_time_cost: Decimal = Field(ge=0)
    fixed_recurring_monthly_cost: Decimal = Field(default=Decimal("0"), ge=0)
    observed_variable_wattage: Decimal = Field(ge=0)
    variable_utility_cost_known: Literal[False] = False
    observed_cash: Decimal
    projected_cash_after: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    source_bridge_sequence: int = Field(ge=1)
    source_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    expires_at: AwareDatetime
    material_unknowns: tuple[str, ...]

    @model_validator(mode="after")
    def validate_commitment(self) -> WorkstationPlan:
        if self.total_one_time_cost != sum(
            (item.expected_cash_charge for item in self.line_items), start=Decimal("0")
        ):
            raise ValueError("plan total does not equal its exact catalog lines")
        purposes = [item.purpose for item in self.reused_components]
        purposes.extend(item.purpose for item in self.line_items)
        if len(purposes) != len(set(purposes)):
            raise ValueError("a workstation component purpose cannot be reused and purchased")
        if self.projected_cash_after != self.observed_cash - self.total_one_time_cost:
            raise ValueError("projected cash does not equal cash less exact one-time cost")
        if self.projected_cash_after < self.minimum_cash_reserve:
            raise ValueError("workstation purchase violates the requested cash reserve")
        if self.fixed_recurring_monthly_cost != 0:
            raise ValueError("this workstation slice does not authorize recurring infrastructure")
        if self.expires_at <= self.created_at:
            raise ValueError("workstation plan expiration must follow creation")
        return self


class WorkstationApproval(WorkstationModel):
    schema_version: Literal[1] = 1
    approval_id: UUID
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool
    resolved_at: AwareDatetime


class WorkstationOperationResult(WorkstationModel):
    schema_version: Literal[1] = 1
    intent: WorkstationIntent
    plan: WorkstationPlan
    approval: WorkstationApproval | None = None
    before: SoftwareIncUIObservation
    after: SoftwareIncUIObservation
    gestures_sent: int = Field(ge=0)
    cycles: int = Field(ge=1)
    dry_run: bool
    verified: bool
    partial: bool = False
    message: str = Field(min_length=1, max_length=2048)
    completed_at: AwareDatetime


ApprovalProvider = Callable[[WorkstationPlan], bool]

_PREPARE = re.compile(
    r"^(?:prepare|build|place|set up|setup|add)\s+(?:one|1|a)\s+(?:valid\s+)?"
    r"workstation\s+(?:for|in)\s+(?P<team>.+?)"
    r"(?:\s+(?:while keeping|with|leaving)\s+(?:at least\s+)?\$?"
    r"(?P<reserve>[\d,]+(?:\.\d{1,2})?)\s+(?:in\s+)?(?:cash|reserve))?$",
    re.IGNORECASE,
)


def parse_workstation_intent(instruction: str) -> WorkstationIntent:
    normalized = " ".join(instruction.strip().split())
    match = _PREPARE.fullmatch(normalized)
    if match is None:
        raise SoftwareIncUIValidationError(
            "unsupported workstation request; use `prepare one workstation for <team>` "
            "with an optional `while keeping $X in reserve`"
        )
    reserve = Decimal("0")
    if match.group("reserve"):
        try:
            reserve = Decimal(match.group("reserve").replace(",", "")).quantize(_MONEY)
        except InvalidOperation as error:
            raise SoftwareIncUIValidationError("cash reserve is not valid USD") from error
    return WorkstationIntent(team_name=match.group("team"), minimum_cash_reserve=reserve)


def build_workstation_plan(
    intent: WorkstationIntent,
    observation: SoftwareIncUIObservation,
    *,
    now: datetime | None = None,
) -> WorkstationPlan:
    snapshot = observation.semantic_after
    team = _unique_named(_complete(snapshot, "teams"), "team", "name", intent.team_name)
    employee_count = _integer(team, "employee_count")
    if employee_count < 1:
        raise SoftwareIncUIValidationError(
            "a workstation requires at least one observed team member"
        )
    rooms = [
        entity
        for entity in _complete(snapshot, "offices").entities
        if entity.entity_type == "office_room"
    ]
    if not rooms:
        raise SoftwareIncUIValidationError("no safe player-owned indoor room is observable")
    assigned = [room for room in rooms if _has_team(room, intent.team_name)]
    existing_capacity = [room for room in assigned if _integer(room, "valid_workstations") >= 1]
    safe_assigned = [room for room in assigned if not _boolean(room, "major_problem")]
    unassigned = [
        room for room in rooms if not _room_teams(room) and not _boolean(room, "major_problem")
    ]
    # Existing valid capacity is idempotent even when the room has another reported
    # problem. A later invocation must not buy a duplicate workstation in a different
    # room merely because the prepared room developed an unrelated problem.
    candidates = existing_capacity or safe_assigned or unassigned
    if not candidates:
        raise SoftwareIncUIValidationError(
            "no assigned or empty room is available; Sim Pilot will not evict another team"
        )
    room = max(
        candidates,
        key=lambda item: (
            _integer(item, "valid_workstations"),
            _number(item, "area"),
            item.entity_id,
        ),
    )
    initial_capacity = _integer(room, "valid_workstations")
    reused: tuple[WorkstationReusedComponent, ...]
    lines: tuple[WorkstationLineItem, ...]
    bundle: tuple[
        tuple[Literal["work_surface", "computer", "chair"], FurnitureCatalogItem], ...
    ] = ()
    room_equipment = tuple(
        entity
        for entity in _complete(snapshot, "offices").entities
        if entity.entity_type == "office_equipment"
        and entity.values.get("room_id") == room.entity_id
    )
    if initial_capacity >= 1:
        reused = ()
        lines = ()
    else:
        catalog = tuple(
            _catalog_item(entity)
            for entity in _complete(snapshot, "build_catalog").entities
            if _catalog_available(entity)
        )
        bundle = _minimal_bundle(catalog)
        reused, lines = _resume_bundle(bundle, room_equipment)
    missing_trashcan = _requires_trashcan_correction(room, room_equipment)
    if missing_trashcan:
        catalog = tuple(
            _catalog_item(entity)
            for entity in _complete(snapshot, "build_catalog").entities
            if _catalog_available(entity)
        )
        trashcan = _trashcan(catalog)
        lines += (
            WorkstationLineItem(
                sequence=len(lines) + 1,
                purpose="trashcan",
                catalog_item=trashcan,
                total_price=trashcan.one_time_cost,
                expected_cash_charge=(
                    Decimal("0") if trashcan.inventory_count > 0 else trashcan.one_time_cost
                ),
            ),
        )
    cash = _cash(snapshot)
    total = sum((line.expected_cash_charge for line in lines), start=Decimal("0"))
    projected = cash - total
    if projected < intent.minimum_cash_reserve:
        raise SoftwareIncUIValidationError(
            f"exact workstation cost ${total:,.2f} would leave ${projected:,.2f}, below the "
            f"requested ${intent.minimum_cash_reserve:,.2f} reserve"
        )
    current = now or datetime.now(UTC)
    previous_teams = _room_teams(room)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "assign_room_to_team": not _has_team(room, intent.team_name),
        "game_session_id": snapshot.game_session_id,
        "items": [line.model_dump(mode="json") for line in lines],
        "reused_components": [item.model_dump(mode="json") for item in reused],
        "minimum_cash_reserve": str(intent.minimum_cash_reserve),
        "expected_room_problem_cleared": missing_trashcan,
        "room_id": room.entity_id,
        "room_teams": previous_teams,
        "save_identity": save_identity,
        "source_frame_id": observation.frame.frame_id,
        "source_projection_id": observation.projection_id,
        "team_id": team.entity_id,
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return WorkstationPlan(
        plan_id=uuid5(NAMESPACE_URL, f"sim-pilot:software-inc:workstation:{fingerprint}"),
        fingerprint=fingerprint,
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        team_id=team.entity_id,
        team_name=_text(team, "name"),
        room_id=room.entity_id,
        assign_room_to_team=not _has_team(room, intent.team_name),
        previous_room_teams=previous_teams,
        initial_valid_workstations=initial_capacity,
        expected_valid_workstations=max(1, initial_capacity),
        expected_room_problem_cleared=missing_trashcan,
        reused_components=reused,
        line_items=lines,
        total_one_time_cost=total,
        observed_variable_wattage=sum((item.wattage for _, item in bundle), start=Decimal("0")),
        observed_cash=cash,
        projected_cash_after=projected,
        minimum_cash_reserve=intent.minimum_cash_reserve,
        source_bridge_sequence=snapshot.bridge_sequence,
        source_frame_id=observation.frame.frame_id,
        source_projection_id=observation.projection_id,
        created_at=current,
        expires_at=current + _PLAN_TTL,
        material_unknowns=(
            "Software Inc. exposes equipment wattage but not a deterministic monthly utility "
            "charge for this placement; approval covers exact purchase prices, not unknown "
            "usage-based electricity.",
            *(
                (
                    "The observed room has a computer, no trashcan, and one major problem. "
                    "Software Inc. 1.8.41's verified room rule requires trash capacity for a "
                    "computer room; the room problem must clear after this one-item correction.",
                )
                if missing_trashcan
                else ()
            ),
        ),
    )


def select_workstation_catalog(
    snapshot: GameSnapshot,
) -> tuple[tuple[Literal["work_surface", "computer", "chair"], FurnitureCatalogItem], ...]:
    """Select the cheapest exact compatible catalog bundle without planning input."""
    catalog = tuple(
        _catalog_item(entity)
        for entity in _complete(snapshot, "build_catalog").entities
        if _catalog_available(entity)
    )
    return _minimal_bundle(catalog)


def resolve_workstation_approval(plan: WorkstationPlan, *, approved: bool) -> WorkstationApproval:
    return WorkstationApproval(
        approval_id=uuid5(NAMESPACE_URL, f"sim-pilot:approval:{plan.fingerprint}"),
        plan_fingerprint=plan.fingerprint,
        approved=approved,
        resolved_at=datetime.now(UTC),
    )


def require_valid_workstation_approval(
    plan: WorkstationPlan,
    approval: WorkstationApproval,
    observation: SoftwareIncUIObservation,
) -> None:
    if not approval.approved:
        raise SoftwareIncUIValidationError("exact workstation purchase approval was denied")
    if approval.plan_fingerprint != plan.fingerprint:
        raise SoftwareIncUIValidationError("approval belongs to a different workstation plan")
    if plan.expires_at <= datetime.now(UTC):
        raise SoftwareIncUIValidationError("workstation approval expired before purchase")
    snapshot = observation.semantic_after
    if snapshot.game_session_id != plan.game_session_id:
        raise SoftwareIncUIValidationError("game session changed after workstation approval")
    if (
        json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
        != plan.save_identity
    ):
        raise SoftwareIncUIValidationError("save identity changed after workstation approval")
    current = _cash(snapshot)
    if current != plan.observed_cash:
        raise SoftwareIncUIValidationError(
            "cash changed after approval; a fresh exact workstation plan is required"
        )
    if current < plan.total_one_time_cost + plan.minimum_cash_reserve:
        raise SoftwareIncUIValidationError(
            "cash changed and no longer satisfies the approved reserve"
        )
    room = _entity(_complete(snapshot, "offices"), "office_room", plan.room_id)
    current_teams = _room_teams(room)
    if any(
        team not in plan.previous_room_teams for team in current_teams if team != plan.team_name
    ):
        raise SoftwareIncUIValidationError("room assignments changed after workstation approval")
    current_catalog = {
        item.item_id: item
        for item in (
            _catalog_item(entity)
            for entity in _complete(snapshot, "build_catalog").entities
            if _catalog_available(entity)
        )
    }
    for line in plan.line_items:
        if current_catalog.get(line.catalog_item.item_id) != line.catalog_item:
            raise SoftwareIncUIValidationError(
                f"catalog identity or price changed for {line.catalog_item.display_name}"
            )
    refreshed = build_workstation_plan(
        WorkstationIntent(
            team_name=plan.team_name,
            minimum_cash_reserve=plan.minimum_cash_reserve,
        ),
        observation,
    )
    if _commitment_identity(refreshed) != _commitment_identity(plan):
        raise SoftwareIncUIValidationError(
            "workstation commitment changed while approval was pending; a fresh approval is "
            "required"
        )


def _commitment_identity(plan: WorkstationPlan) -> tuple[object, ...]:
    """Exclude only ephemeral frame, sequence, timing, and derived approval identity."""
    return (
        plan.game_session_id,
        plan.save_identity,
        plan.team_id,
        plan.team_name,
        plan.room_id,
        plan.assign_room_to_team,
        plan.previous_room_teams,
        plan.initial_valid_workstations,
        plan.expected_valid_workstations,
        plan.expected_room_problem_cleared,
        plan.reused_components,
        plan.line_items,
        plan.total_one_time_cost,
        plan.fixed_recurring_monthly_cost,
        plan.observed_variable_wattage,
        plan.observed_cash,
        plan.projected_cash_after,
        plan.minimum_cash_reserve,
    )


def verify_workstation_result(
    before: GameSnapshot,
    after: GameSnapshot,
    plan: WorkstationPlan,
) -> None:
    if before.game_session_id != after.game_session_id:
        raise SoftwareIncUIVerificationError("game session changed during workstation setup")
    before_room = _entity(_complete(before, "offices"), "office_room", plan.room_id)
    after_room = _entity(_complete(after, "offices"), "office_room", plan.room_id)
    after_teams = _room_teams(after_room)
    if plan.team_name not in after_teams:
        raise SoftwareIncUIVerificationError("target room was not assigned to the requested team")
    if any(team not in plan.previous_room_teams and team != plan.team_name for team in after_teams):
        raise SoftwareIncUIVerificationError("an unrelated team was assigned to the target room")
    if _integer(after_room, "valid_workstations") < plan.expected_valid_workstations:
        raise SoftwareIncUIVerificationError("one valid workstation was not observed after setup")
    if plan.expected_room_problem_cleared and (
        _boolean(after_room, "major_problem") or _integer(after_room, "problem_count") != 0
    ):
        raise SoftwareIncUIVerificationError(
            "the approved trash-capacity correction did not clear the room problem"
        )
    if _integer(before_room, "valid_workstations") != plan.initial_valid_workstations:
        raise SoftwareIncUIVerificationError("initial room capacity no longer matches the plan")
    expected_delta = plan.total_one_time_cost
    actual_delta = _cash(before) - _cash(after)
    if actual_delta != expected_delta:
        raise SoftwareIncUIVerificationError(
            f"cash changed by ${actual_delta:,.2f}; exact approved purchase total was "
            f"${expected_delta:,.2f}"
        )


def _minimal_bundle(
    catalog: tuple[FurnitureCatalogItem, ...],
) -> tuple[tuple[Literal["work_surface", "computer", "chair"], FurnitureCatalogItem], ...]:
    unique = _unique_search_titles(catalog)
    computers = [
        item
        for item in unique
        if item.furniture_type.casefold() == "computer" and item.can_assign and item.needs_chair
    ]
    if not computers:
        raise SoftwareIncUIValidationError(
            "no unique, enabled Computer catalog item exposes the verified workstation contract"
        )
    computer = min(computers, key=_catalog_order)
    surfaces = [
        item
        for item in unique
        if item.furniture_type.casefold() in {"desk", "table"}
        and (not computer.snaps_to or bool(set(computer.snaps_to).intersection(item.snap_points)))
    ]
    if not surfaces:
        raise SoftwareIncUIValidationError(
            "no unique searchable desk/table exposes a compatible Computer snap point"
        )
    surface = min(surfaces, key=_catalog_order)
    chairs = [
        item
        for item in unique
        if "chair" in item.furniture_type.casefold() or "chair" in item.display_name.casefold()
    ]
    compatible_chairs = [
        item
        for item in chairs
        if not item.snaps_to or bool(set(item.snaps_to).intersection(surface.snap_points))
    ]
    if not compatible_chairs:
        raise SoftwareIncUIValidationError(
            "no unique searchable chair exposes a compatible desk/table snap point"
        )
    chair = min(compatible_chairs, key=_catalog_order)
    return (("work_surface", surface), ("computer", computer), ("chair", chair))


def _requires_trashcan_correction(
    room: ObservedEntity, equipment: tuple[ObservedEntity, ...]
) -> bool:
    if not _boolean(room, "major_problem") or _integer(room, "problem_count") != 1:
        return False
    has_computer = any(
        _text(item, "function_category", allow_empty=True).casefold() == "computer"
        for item in equipment
    )
    has_trashcan = any(
        _text(item, "type", allow_empty=True).casefold() == "trashcan" for item in equipment
    )
    return has_computer and not has_trashcan


def _trashcan(catalog: tuple[FurnitureCatalogItem, ...]) -> FurnitureCatalogItem:
    matches = [
        item
        for item in _unique_search_titles(catalog)
        if item.furniture_type.casefold() == "trashcan"
    ]
    if not matches:
        raise SoftwareIncUIValidationError(
            "the computer room lacks trash capacity, but no unique enabled Trashcan catalog "
            "item is currently observable"
        )
    return min(matches, key=_catalog_order)


def _resume_bundle(
    bundle: tuple[tuple[Literal["work_surface", "computer", "chair"], FurnitureCatalogItem], ...],
    equipment: tuple[ObservedEntity, ...],
) -> tuple[tuple[WorkstationReusedComponent, ...], tuple[WorkstationLineItem, ...]]:
    remaining = sorted(equipment, key=lambda item: item.entity_id)
    reused: list[WorkstationReusedComponent] = []
    missing: list[tuple[Literal["work_surface", "computer", "chair"], FurnitureCatalogItem]] = []
    for purpose, item in bundle:
        matches = [
            entity
            for entity in remaining
            if entity.values.get("prefab_name") == item.prefab_name
            and entity.values.get("valid") is True
            and entity.values.get("blocked") is False
        ]
        if not matches:
            missing.append((purpose, item))
            continue
        match = matches[0]
        remaining.remove(match)
        reused.append(
            WorkstationReusedComponent(
                purpose=purpose,
                equipment_id=match.entity_id,
                prefab_name=item.prefab_name,
                display_name=item.display_name,
            )
        )
    lines = tuple(
        WorkstationLineItem(
            sequence=index,
            purpose=purpose,
            catalog_item=item,
            total_price=item.one_time_cost,
            expected_cash_charge=(Decimal("0") if item.inventory_count > 0 else item.one_time_cost),
        )
        for index, (purpose, item) in enumerate(missing, start=1)
    )
    return tuple(reused), lines


def _unique_search_titles(
    catalog: tuple[FurnitureCatalogItem, ...],
) -> tuple[FurnitureCatalogItem, ...]:
    grouped: dict[str, list[FurnitureCatalogItem]] = {}
    for item in catalog:
        grouped.setdefault(item.search_title.casefold(), []).append(item)
    return tuple(item for items in grouped.values() if len(items) == 1 for item in items)


def _catalog_order(item: FurnitureCatalogItem) -> tuple[Decimal, Decimal, str]:
    return item.one_time_cost, item.wattage, item.item_id


def _catalog_item(entity: ObservedEntity) -> FurnitureCatalogItem:
    if entity.entity_type != "furniture_catalog_item":
        raise SoftwareIncUIValidationError("build catalog contains an unexpected entity type")
    if not _boolean(entity, "searchable") or not _boolean(entity, "search_enabled"):
        raise SoftwareIncUIValidationError(
            f"catalog item {entity.entity_id} is not currently available through global search"
        )
    if _boolean(entity, "construction") or not _boolean(entity, "valid_indoors"):
        raise SoftwareIncUIValidationError(
            f"catalog item {entity.entity_id} is not supported indoor furniture"
        )
    cost = _decimal(entity, "one_time_cost")
    if cost <= 0:
        raise SoftwareIncUIValidationError(
            f"catalog item {entity.entity_id} does not expose a positive exact price"
        )
    return FurnitureCatalogItem(
        item_id=entity.entity_id,
        display_name=_text(entity, "display_name"),
        prefab_name=_text(entity, "prefab_name"),
        furniture_type=_text(entity, "type", allow_empty=True),
        search_title=_text(entity, "search_title"),
        one_time_cost=cost,
        wattage=max(Decimal("0"), _decimal(entity, "wattage")),
        computer_power=max(Decimal("0"), _decimal(entity, "computer_power")),
        inventory_count=_integer(entity, "inventory_count"),
        can_assign=_boolean(entity, "can_assign"),
        needs_chair=_boolean(entity, "needs_chair"),
        is_snapping=_boolean(entity, "is_snapping"),
        snaps_to=_strings(entity, "snaps_to"),
        snap_points=_strings(entity, "snap_points"),
        categories=_strings(entity, "categories"),
        function_category=_text(entity, "function_category", allow_empty=True),
    )


def _catalog_available(entity: ObservedEntity) -> bool:
    return (
        entity.entity_type == "furniture_catalog_item"
        and entity.values.get("searchable") is True
        and entity.values.get("search_enabled") is True
        and entity.values.get("construction") is False
        and entity.values.get("valid_indoors") is True
        and isinstance(entity.values.get("one_time_cost"), (int, float))
        and not isinstance(entity.values.get("one_time_cost"), bool)
        and Decimal(str(entity.values["one_time_cost"])) > 0
    )


def _complete(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1 or matches[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise SoftwareIncUIValidationError(f"complete {name} observation is required")
    return matches[0]


def _entity(surface: ObservationSurface, entity_type: str, entity_id: str) -> ObservedEntity:
    matches = [
        entity
        for entity in surface.entities
        if entity.entity_type == entity_type and entity.entity_id == entity_id
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"{entity_type} {entity_id!r} did not resolve once")
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
        raise SoftwareIncUIValidationError(f"{entity_type} {requested!r} did not resolve once")
    return matches[0]


def _room_teams(room: ObservedEntity) -> tuple[str, ...]:
    return tuple(sorted(filter(None, _text(room, "assigned_teams", allow_empty=True).split("|"))))


def _has_team(room: ObservedEntity, team_name: str) -> bool:
    return team_name.casefold() in {value.casefold() for value in _room_teams(room)}


def _cash(snapshot: GameSnapshot) -> Decimal:
    surfaces = [surface for surface in snapshot.surfaces if surface.coverage.surface == "finances"]
    if len(surfaces) != 1 or surfaces[0].coverage.status not in {
        CoverageStatus.OBSERVED_COMPLETE,
        CoverageStatus.OBSERVED_PARTIAL,
    }:
        raise SoftwareIncUIValidationError("observed company cash is required")
    entities = [
        entity for entity in surfaces[0].entities if entity.entity_type == "company_finances"
    ]
    if len(entities) != 1:
        raise SoftwareIncUIValidationError("company finance entity did not resolve once")
    return _decimal(entities[0], "cash").quantize(_MONEY)


def _text(entity: ObservedEntity, field: str, *, allow_empty: bool = False) -> str:
    value = entity.values.get(field)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed text")
    return value


def _strings(entity: ObservedEntity, field: str) -> tuple[str, ...]:
    return tuple(sorted(filter(None, _text(entity, field, allow_empty=True).split("|"))))


def _boolean(entity: ObservedEntity, field: str) -> bool:
    value = entity.values.get(field)
    if not isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed boolean")
    return value


def _integer(entity: ObservedEntity, field: str) -> int:
    value = entity.values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed integer")
    return value


def _number(entity: ObservedEntity, field: str) -> Decimal:
    return _decimal(entity, field)


def _decimal(entity: ObservedEntity, field: str) -> Decimal:
    value = entity.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is invalid") from error
    if not result.is_finite():
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not finite")
    return result


__all__ = [
    "ApprovalProvider",
    "FurnitureCatalogItem",
    "WorkstationApproval",
    "WorkstationIntent",
    "WorkstationLineItem",
    "WorkstationOperationResult",
    "WorkstationPlan",
    "WorkstationReusedComponent",
    "build_workstation_plan",
    "parse_workstation_intent",
    "require_valid_workstation_approval",
    "resolve_workstation_approval",
    "select_workstation_catalog",
    "verify_workstation_result",
]
