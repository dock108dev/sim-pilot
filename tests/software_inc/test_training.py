"""Prompt 6B education policy, persistence, and reconciliation tests."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

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
from sim_pilot.software_inc.training import (
    TrainingIntentAction,
    TrainingWorkflowStatus,
    parse_training_intent,
    recommend_training,
)
from sim_pilot.software_inc.training.store import TrainingWorkflowStore, store_is_owner_only
from sim_pilot.software_inc.training.workflow import (
    create_training_workflow,
    resolve_training_approval,
    synchronize_training,
)


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
    sequence: int = 10,
    *,
    cash: float = 100_000,
    founder_course: str = "",
    founder_level: int = 0,
    work_active: bool = False,
) -> GameSnapshot:
    employees = (
        ObservedEntity(
            entity_type="employee",
            entity_id="100",
            values={
                "courses": founder_course,
                "dismissed": False,
                "founder": True,
                "last_course": "January 1980",
                "name": "Alex Founder",
                "role": "Designer",
                "salary": 2_000.0,
                "skill_designer": 0.8,
                "taking_courses": bool(founder_course),
                "team": "Core",
            },
        ),
        ObservedEntity(
            entity_type="employee",
            entity_id="101",
            values={
                "courses": "",
                "dismissed": False,
                "founder": False,
                "last_course": "January 1980",
                "name": "Blair Designer",
                "role": "Designer",
                "salary": 3_000.0,
                "skill_designer": 0.6,
                "taking_courses": False,
                "team": "Core",
            },
        ),
    )
    education = (
        ObservedEntity(
            entity_type="education_rule",
            entity_id="current",
            values={"duration_months": 1},
        ),
        ObservedEntity(
            entity_type="employee_specialization",
            entity_id="100:Designer:System",
            values={
                "employee_id": "100",
                "employee_name": "Alex Founder",
                "level": founder_level,
                "one_time_cost": (600.0, 2_000.0, 5_000.0, 5_000.0)[founder_level],
                "role": "Designer",
                "specialization": "System",
                "team": "Core",
            },
        ),
        ObservedEntity(
            entity_type="employee_specialization",
            entity_id="101:Designer:System",
            values={
                "employee_id": "101",
                "employee_name": "Blair Designer",
                "level": 1,
                "one_time_cost": 2_000.0,
                "role": "Designer",
                "specialization": "System",
                "team": "Core",
            },
        ),
    )
    work_items = (
        (
            ObservedEntity(
                entity_type="work_item",
                entity_id="work-1",
                values={"assigned_teams": "Core", "done": False, "name": "Atlas"},
            ),
        )
        if work_active
        else ()
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge-v9",
        game_session_id="session-1",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v9",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not applicable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="training-save"),
        game_state={
            "current_time": "January 1980",
            "force_pause": True,
            "simulation_speed": "0",
        },
        surfaces=(
            _surface("education", education),
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
            _surface(
                "teams",
                (
                    ObservedEntity(
                        entity_type="team",
                        entity_id="core",
                        values={"employee_count": 2, "name": "Core"},
                    ),
                ),
            ),
            _surface("work_items", work_items),
        ),
    )


def test_recommendation_selects_suitable_employee_and_reports_exact_economics() -> None:
    recommendation = recommend_training(
        _snapshot(), team_name="Core", minimum_cash_reserve=Decimal("50000")
    )
    candidate = recommendation.recommended
    assert candidate is not None
    assert candidate.employee.employee_name == "Alex Founder"
    assert candidate.course_duration_months == 1
    assert candidate.current_course_cost == Decimal("600.0")
    assert candidate.projected_direct_cost == Decimal("7600.0")
    assert candidate.payroll_during_training == Decimal("6000.0")
    assert candidate.team_capacity_before == 2
    assert candidate.team_capacity_during == 1
    assert candidate.cash_after_projected_cost == Decimal("92400.0")
    assert len(recommendation.alternatives) == 0


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (_snapshot(work_active=True), "displaced"),
        (_snapshot(cash=5_500), "reserve"),
        (_snapshot(founder_course="Designer:System"), "active education"),
    ],
)
def test_policy_rejects_unsafe_candidates(snapshot: GameSnapshot, reason: str) -> None:
    recommendation = recommend_training(
        snapshot, team_name="Core", minimum_cash_reserve=Decimal("5000")
    )
    assert recommendation.recommended is None
    assert any(reason in item for item in recommendation.rejection_reasons)


def test_workflow_approval_reconciliation_and_completion() -> None:
    initial = _snapshot()
    candidate = recommend_training(
        initial, team_name="Core", minimum_cash_reserve=Decimal("50000")
    ).recommended
    assert candidate is not None
    workflow = create_training_workflow(initial, candidate)
    assert workflow.status is TrainingWorkflowStatus.WAITING_FOR_APPROVAL
    approved = resolve_training_approval(workflow, approved=True)
    active = synchronize_training(
        approved, _snapshot(11, cash=99_400, founder_course="Designer:System")
    )
    assert active.status is TrainingWorkflowStatus.ACTIVE
    stage_two = synchronize_training(active, _snapshot(12, cash=99_400, founder_level=1))
    assert stage_two.status is TrainingWorkflowStatus.WAITING_FOR_APPROVAL
    assert stage_two.current_level == 1
    assert stage_two.pending_approval is not None
    assert stage_two.pending_approval.direct_cost == Decimal("2000.0")
    stage_two = resolve_training_approval(stage_two, approved=True)
    active_two = synchronize_training(
        stage_two, _snapshot(13, cash=97_400, founder_course="Designer:System", founder_level=1)
    )
    stage_three = synchronize_training(active_two, _snapshot(14, cash=97_400, founder_level=2))
    assert stage_three.status is TrainingWorkflowStatus.WAITING_FOR_APPROVAL
    assert stage_three.pending_approval is not None
    assert stage_three.pending_approval.direct_cost == Decimal("5000.0")
    stage_three = resolve_training_approval(stage_three, approved=True)
    active_three = synchronize_training(
        stage_three,
        _snapshot(15, cash=92_400, founder_course="Designer:System", founder_level=2),
    )
    completed = synchronize_training(active_three, _snapshot(16, cash=92_400, founder_level=3))
    assert completed.status is TrainingWorkflowStatus.COMPLETED
    assert completed.current_level == 3
    with pytest.raises(SoftwareIncUIValidationError, match="fresh bridge sequence"):
        synchronize_training(completed, _snapshot(16, founder_level=3))


def test_owner_only_store_enforces_one_open_workflow(tmp_path: Path) -> None:
    snapshot = _snapshot()
    candidate = recommend_training(
        snapshot, team_name="Core", minimum_cash_reserve=Decimal("50000")
    ).recommended
    assert candidate is not None
    workflow = create_training_workflow(snapshot, candidate)
    store = TrainingWorkflowStore(tmp_path / "training.sqlite3")
    store.save(workflow)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    assert store.current(game_session_id="session-1", save_identity=save_identity) == workflow
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store_is_owner_only(store.path)


def test_plain_english_requires_exact_team_duration_domain_and_reserve() -> None:
    intent = parse_training_intent(
        "train one suitable employee from Core in System design for three months "
        "while keeping $50,000 in cash"
    )
    assert intent.action is TrainingIntentAction.START
    assert intent.team_name == "Core"
    assert intent.minimum_cash_reserve == Decimal("50000.00")
    with pytest.raises(SoftwareIncUIValidationError, match="unsupported education request"):
        parse_training_intent("train Core")
