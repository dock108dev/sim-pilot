"""Software Inc. staffing intent, policy, approval, and semantic verification."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from PIL import Image

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
from sim_pilot.software_inc.errors import (
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
)
from sim_pilot.software_inc.ui.staffing import (
    applicant_observations,
    build_staffing_plan,
    hiring_search_observation,
    parse_staffing_intent,
    pending_approval,
    require_team_absent,
    require_valid_approval,
    resolve_approval,
    select_applicant,
    verify_applicant_search,
    verify_employee_hired,
    verify_team_created,
)
from tests.software_inc.test_ui_control import capture_fixture


def _surface(
    name: str,
    entities: tuple[ObservedEntity, ...] = (),
    *,
    status: CoverageStatus = CoverageStatus.OBSERVED_COMPLETE,
) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(surface=name, status=status, fields=()),
        entities=tuple(sorted(entities, key=lambda item: (item.entity_type, item.entity_id))),
    )


def _team(identity: str, name: str, count: int) -> ObservedEntity:
    return ObservedEntity(
        entity_type="team",
        entity_id=identity,
        values={"name": name, "employee_count": count},
    )


def _employee(
    identity: str,
    name: str,
    *,
    team: str,
    salary: float,
    role: str = "Programmer",
) -> ObservedEntity:
    return ObservedEntity(
        entity_type="employee",
        entity_id=identity,
        values={"name": name, "role": role, "salary": salary, "team": team},
    )


def _applicant(
    identity: str,
    name: str,
    *,
    salary: float,
    index: int,
    role: str = "Programmer",
    team: str = "Support Alpha",
) -> ObservedEntity:
    return ObservedEntity(
        entity_type="applicant",
        entity_id=identity,
        values={
            "available": True,
            "display_index": index,
            "name": name,
            "role": role,
            "salary": salary,
            "salary_period": "monthly",
            "selected_team": team,
            "wage_bracket": "Low",
        },
    )


def _snapshot(
    sequence: int,
    *,
    teams: tuple[ObservedEntity, ...] = (_team("core", "Core", 1),),
    employees: tuple[ObservedEntity, ...] = (
        _employee("founder", "Founder", team="Core", salary=0.0, role="Founder"),
    ),
    applicants: tuple[ObservedEntity, ...] = (),
    cash: float = 100_000,
    staffing_scene: str = "manage_teams",
    search_cost_text: str = "$9,000",
) -> GameSnapshot:
    staffing_state = ObservedEntity(
        entity_type="staffing_ui_state",
        entity_id="current",
        values={
            "scene": staffing_scene,
            "team_name_value": "",
            "team_name_focused": False,
            "selected_team": "Support Alpha",
            "selected_applicant_indices": "",
            "role": "Programmer",
            "wage_bracket": "Low",
            "search_cost_text": search_cost_text,
            "pool_text": "10 applicants",
        },
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge",
        game_session_id="session",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="unavailable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="disposable"),
        game_state={"force_pause": True, "simulation_speed": "0"},
        surfaces=tuple(
            sorted(
                (
                    _surface("applicants", applicants),
                    _surface("company"),
                    _surface("employees", employees),
                    _surface(
                        "finances",
                        (
                            ObservedEntity(
                                entity_type="company_finances",
                                entity_id="company",
                                values={"cash": cash},
                            ),
                        ),
                        status=CoverageStatus.OBSERVED_PARTIAL,
                    ),
                    _surface("game_state"),
                    _surface("offices"),
                    _surface("products"),
                    _surface("staffing_ui", (staffing_state,)),
                    _surface("teams", teams),
                    _surface("work_items"),
                ),
                key=lambda surface: surface.coverage.surface,
            )
        ),
    )


def _observation(snapshot: GameSnapshot) -> SoftwareIncUIObservation:
    capture = capture_fixture(Image.new("RGB", (1200, 800)), sequence=1)
    return SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot,
        frame=capture.metadata,
        scene=SoftwareIncUIScene.MANAGE_TEAMS,
        modal_state=ModalState.NONE,
        projection_id="a" * 64,
        targets=(),
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0.1,
        semantic_capture_skew_seconds=0.05,
    )


def test_parses_bounded_team_and_hiring_requests() -> None:
    created = parse_staffing_intent("Create a team named Support Alpha.")
    assert created.action is SoftwareIncUIAction.CREATE_TEAM
    assert created.team_name == "Support Alpha"

    hired = parse_staffing_intent(
        "Hire one programmer for Support Alpha for no more than $8,000 per month"
    )
    assert hired.action is SoftwareIncUIAction.HIRE_EMPLOYEE
    assert hired.maximum_monthly_salary == Decimal("8000.00")

    with pytest.raises(SoftwareIncUIValidationError, match="explicit USD monthly salary cap"):
        parse_staffing_intent("hire ten developers")


def test_duplicate_team_is_case_and_whitespace_insensitive() -> None:
    snapshot = _snapshot(1, teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)))
    with pytest.raises(SoftwareIncUIValidationError, match="already exists"):
        require_team_absent(snapshot, " support   alpha ")


def test_selects_lowest_cost_eligible_programmer_deterministically() -> None:
    snapshot = _snapshot(
        1,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)),
        applicants=(
            _applicant("20", "Costly", salary=7900, index=0),
            _applicant("10", "Affordable", salary=6200, index=1),
            _applicant("30", "Artist", salary=5000, index=2, role="Artist"),
        ),
    )
    observed = applicant_observations(snapshot)
    assert [item.applicant_id for item in observed] == ["20", "10", "30"]
    selected = select_applicant(
        snapshot,
        team_name="Support Alpha",
        role="Programmer",
        maximum_monthly_salary=Decimal("8000"),
    )
    assert selected.applicant_id == "10"


def test_exact_plan_approval_expires_on_applicant_change() -> None:
    snapshot = _snapshot(
        1,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)),
        applicants=(_applicant("10", "Affordable", salary=6200, index=0),),
    )
    intent = parse_staffing_intent(
        "Hire one programmer for Support Alpha for no more than $8,000 per month"
    )
    observation = _observation(snapshot)
    plan = build_staffing_plan(intent, observation)
    approval = resolve_approval(pending_approval(plan), approved=True)
    require_valid_approval(plan, approval, observation)

    changed_snapshot = _snapshot(
        2,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)),
        applicants=(_applicant("10", "Affordable", salary=6300, index=0),),
    )
    with pytest.raises(SoftwareIncUIValidationError, match="changed after approval"):
        require_valid_approval(plan, approval, _observation(changed_snapshot))


def test_paid_applicant_search_requires_exact_cost_and_verifies_cash_delta() -> None:
    teams = (_team("core", "Core", 1), _team("support", "Support Alpha", 0))
    before = _snapshot(
        1,
        teams=teams,
        cash=100_000,
        staffing_scene="hiring_setup",
        search_cost_text="Search cost: $9,000",
    )
    intent = parse_staffing_intent(
        "Observe programmer applicants for Support Alpha under $8,000 per month"
    )
    search = hiring_search_observation(before)
    assert search.one_time_cost == Decimal("9000.00")
    plan = build_staffing_plan(intent, _observation(before))
    approval = resolve_approval(pending_approval(plan), approved=True)
    require_valid_approval(plan, approval, _observation(before))

    after = _snapshot(
        2,
        teams=teams,
        applicants=(_applicant("10", "Affordable", salary=6200, index=0),),
        cash=91_000,
        staffing_scene="applicant_list",
    )
    assert verify_applicant_search(before, after, plan=plan)[0].applicant_id == "10"

    wrong_charge = _snapshot(
        3,
        teams=teams,
        applicants=(_applicant("10", "Affordable", salary=6200, index=0),),
        cash=90_000,
        staffing_scene="applicant_list",
    )
    with pytest.raises(SoftwareIncUIVerificationError, match="one-time cost"):
        verify_applicant_search(before, wrong_charge, plan=plan)


def test_verifies_exact_team_creation_delta() -> None:
    before = _snapshot(1)
    after = _snapshot(2, teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)))
    created = verify_team_created(before, after, team_name="Support Alpha")
    assert created.entity_id == "support"

    wrong = _snapshot(
        3,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 0)),
        employees=(
            _employee("founder", "Founder", team="Core", salary=0.0, role="Founder"),
            _employee("extra", "Unexpected", team="Support Alpha", salary=1000),
        ),
    )
    with pytest.raises(SoftwareIncUIVerificationError, match="changed employees"):
        verify_team_created(before, wrong, team_name="Support Alpha")


def test_verifies_hire_assignment_salary_and_recurring_payroll() -> None:
    teams_before = (_team("core", "Core", 1), _team("support", "Support Alpha", 0))
    applicants = (_applicant("10", "Affordable", salary=6200, index=0),)
    before = _snapshot(1, teams=teams_before, applicants=applicants)
    intent = parse_staffing_intent(
        "Hire one programmer for Support Alpha for no more than $8,000 per month"
    )
    plan = build_staffing_plan(intent, _observation(before))
    after = _snapshot(
        2,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 1)),
        employees=(
            _employee("founder", "Founder", team="Core", salary=0.0, role="Founder"),
            _employee("10", "Affordable", team="Support Alpha", salary=6200),
        ),
    )
    hired = verify_employee_hired(before, after, plan=plan)
    assert hired.entity_id == "10"

    wrong_salary = _snapshot(
        3,
        teams=(_team("core", "Core", 1), _team("support", "Support Alpha", 1)),
        employees=(
            _employee("founder", "Founder", team="Core", salary=0.0, role="Founder"),
            _employee("10", "Affordable", team="Support Alpha", salary=8200),
        ),
    )
    with pytest.raises(SoftwareIncUIVerificationError, match="salary"):
        verify_employee_hired(before, wrong_salary, plan=plan)
