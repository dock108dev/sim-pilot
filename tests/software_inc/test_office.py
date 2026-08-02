"""Office-readiness contracts, policies, and semantic verification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from PIL import Image
from pydantic import ValidationError

from sim_pilot.game_bridge import (
    Architecture,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI
from sim_pilot.software_inc.ui.office import (
    OfficePurchaseApproval,
    parse_office_intent,
    project_team_readiness,
    verify_employee_role,
    verify_working_hours,
)
from sim_pilot.software_inc.ui.office_controller import execute_office_intent
from tests.software_inc.test_ui_control import capture_fixture


def _surface(
    name: str,
    entities: tuple[ObservedEntity, ...] = (),
    *,
    status: CoverageStatus = CoverageStatus.OBSERVED_COMPLETE,
) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(surface=name, status=status, fields=()),
        entities=entities,
    )


def _snapshot(
    *,
    start: int = 8,
    end: int = 16,
    role: str = "Designer",
    room_capacity: int = 1,
    spare_capacity: int = 1,
) -> GameSnapshot:
    surfaces = (
        _surface("applicants"),
        _surface(
            "build_catalog",
            tuple(
                ObservedEntity(
                    entity_type="furniture_catalog_item",
                    entity_id=identity,
                    values={
                        "can_assign": kind == "Computer",
                        "categories": "Office",
                        "computer_power": 1 if kind == "Computer" else 0,
                        "construction": False,
                        "display_name": name,
                        "function_category": "Work",
                        "inventory_count": 0,
                        "is_snapping": kind != "Desk",
                        "needs_chair": kind == "Computer",
                        "one_time_cost": cost,
                        "prefab_name": identity.split(":", maxsplit=1)[0],
                        "search_enabled": True,
                        "search_title": name,
                        "searchable": True,
                        "snap_points": "AtTable|OnTable" if kind == "Desk" else "",
                        "snaps_to": (
                            "OnTable"
                            if kind == "Computer"
                            else "AtTable"
                            if kind == "Chair"
                            else ""
                        ),
                        "type": kind,
                        "valid_indoors": True,
                        "wattage": 20 if kind == "Computer" else 0,
                    },
                )
                for identity, name, kind, cost in (
                    ("Cheap Desk:0", "Cheap Desk", "Desk", 100),
                    ("Modern Computer:0", "Modern Computer", "Computer", 500),
                    ("Office Chair:0", "Office Chair", "Chair", 50),
                )
            ),
        ),
        _surface("build_ui"),
        _surface(
            "company",
            (ObservedEntity(entity_type="company", entity_id="1", values={"name": "Lab"}),),
        ),
        _surface(
            "employees",
            (
                ObservedEntity(
                    entity_type="employee",
                    entity_id="employee-1",
                    values={
                        "name": "Ada",
                        "role": role,
                        "team": "Core",
                        "salary": 5000,
                    },
                ),
            ),
        ),
        _surface(
            "finances",
            (
                ObservedEntity(
                    entity_type="company_finances",
                    entity_id="1",
                    values={"cash": 100000, "valuation": 110000},
                ),
            ),
            status=CoverageStatus.OBSERVED_PARTIAL,
        ),
        _surface("game_state"),
        _surface(
            "infrastructure",
            (
                ObservedEntity(
                    entity_type="server_group",
                    entity_id="Cloud",
                    values={
                        "name": "Cloud",
                        "display_name": "Cloud",
                        "is_cloud": True,
                        "available": 1,
                        "broken": False,
                        "server_count": 0,
                        "item_count": 0,
                        "recurring_cost": 50,
                        "total_power": 0,
                    },
                ),
            ),
        ),
        _surface("office_ui"),
        _surface(
            "offices",
            (
                ObservedEntity(
                    entity_type="office_room",
                    entity_id="room-core",
                    values={
                        "floor": 0,
                        "assigned_teams": "Core",
                        "assignable_workstations": room_capacity,
                        "valid_workstations": room_capacity,
                        "available_workstations": 0,
                        "total_furniture": 4,
                        "major_problem": False,
                        "problem_count": 0,
                        "is_lit": True,
                        "environment": 1,
                        "temperature": 21,
                        "acoustics": 0.5,
                    },
                ),
                ObservedEntity(
                    entity_type="office_room",
                    entity_id="room-spare",
                    values={
                        "floor": 0,
                        "assigned_teams": "",
                        "assignable_workstations": spare_capacity,
                        "valid_workstations": spare_capacity,
                        "available_workstations": spare_capacity,
                        "total_furniture": 2,
                        "major_problem": False,
                        "problem_count": 0,
                        "is_lit": True,
                        "environment": 0,
                        "temperature": 21,
                        "acoustics": 0,
                    },
                ),
            ),
        ),
        _surface("products", status=CoverageStatus.OBSERVED_PARTIAL),
        _surface("staffing_ui"),
        _surface(
            "teams",
            (
                ObservedEntity(
                    entity_type="team",
                    entity_id="core",
                    values={
                        "name": "Core",
                        "employee_count": 1,
                        "work_start": start,
                        "work_end": end,
                    },
                ),
            ),
        ),
        _surface("work_items", status=CoverageStatus.OBSERVED_PARTIAL),
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=1,
        bridge_instance_id="bridge",
        game_session_id="session",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="unavailable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="save"),
        game_state={"force_pause": True, "simulation_speed": "0"},
        surfaces=surfaces,
    )


def test_parse_bounded_schedule_and_role_intents() -> None:
    schedule = parse_office_intent("set Core working hours to 7-15")
    role = parse_office_intent("assign Ada as Programmer for Core")

    assert schedule.action is SoftwareIncUIAction.SET_TEAM_WORKING_HOURS
    assert (schedule.work_start, schedule.work_end) == (Decimal("7"), Decimal("15"))
    assert role.action is SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE
    assert role.employee_name == "Ada" and role.role is not None


@pytest.mark.parametrize(
    "instruction",
    (
        "set Core working hours to 18-8",
        "set Core working hours to 7:30-15",
        "assign Ada as Marketing for Core",
        "assign Ada employee role Programmer",
    ),
)
def test_ambiguous_or_unsafe_office_intent_is_rejected(instruction: str) -> None:
    with pytest.raises((SoftwareIncUIValidationError, ValidationError)):
        parse_office_intent(instruction)


def test_readiness_prefers_existing_capacity_and_never_infers_server_requirement() -> None:
    result = project_team_readiness(_snapshot(room_capacity=0), "Core")

    assert result.current_capacity == 0
    assert result.required_capacity == 1
    assert result.exact_missing_resource == (
        "assign 1 existing valid workstation(s) from empty room(s) room-spare"
    )
    assert result.cheaper_existing_capacity == ("room-spare",)
    assert result.one_time_cost == 0
    assert result.cash_reserve_after_purchase == 100000
    assert result.source_control_required is False
    assert len(result.servers) == 1


def test_readiness_reports_exact_catalog_bundle_when_existing_capacity_is_absent() -> None:
    result = project_team_readiness(
        _snapshot(room_capacity=0, spare_capacity=0),
        "Core",
    )

    assert result.exact_missing_resource == ("1x Cheap Desk; 1x Modern Computer; 1x Office Chair")
    assert result.one_time_cost == Decimal("650")
    assert result.recurring_cost == 0
    assert result.cash_reserve_after_purchase == Decimal("99350")


def test_exact_purchase_approval_separates_recurring_authority() -> None:
    with pytest.raises(ValidationError, match="separate authority"):
        OfficePurchaseApproval(
            item_name="Server",
            quantity=1,
            unit_price=Decimal("1000"),
            total_price=Decimal("1000"),
            projected_cash_after=Decimal("99000"),
            minimum_cash_reserve=Decimal("50000"),
            recurring_monthly_cost=Decimal("100"),
            recurring_cost_authorized=False,
        )


def test_schedule_and_role_postconditions_are_exact() -> None:
    before = _snapshot(start=8, end=16, role="Designer")
    schedule_after = _snapshot(start=7, end=15, role="Designer")
    role_after = _snapshot(start=8, end=16, role="Designer, Programmer")
    schedule = parse_office_intent("set Core working hours to 7-15")
    role = parse_office_intent("assign Ada as Programmer for Core")

    verify_working_hours(before, schedule_after, schedule)
    verify_employee_role(before, role_after, role)


def test_already_satisfied_schedule_sends_zero_input() -> None:
    snapshot = _snapshot(start=8, end=16)
    capture = capture_fixture(Image.new("RGB", (1200, 800), (40, 50, 60)))
    observation = SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot.model_copy(update={"bridge_sequence": 2}),
        frame=capture.metadata,
        scene=SoftwareIncUIScene.MANAGE_TEAMS,
        modal_state=ModalState.NONE,
        projection_id="a" * 64,
        targets=(),
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0,
        semantic_capture_skew_seconds=0,
    )

    class Backend:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("idempotent schedule must not send input")

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return ObservedSoftwareIncUI(observation, capture)

    result = asyncio.run(
        execute_office_intent(
            parse_office_intent("set Core working hours to 8-16"),
            observer_factory=Observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )

    assert result.verified and result.gestures_sent == 0
