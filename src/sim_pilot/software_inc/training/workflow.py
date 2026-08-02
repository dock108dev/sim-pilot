"""Identity-bound state transitions and exact education approval."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import (
    TrainingApproval,
    TrainingCandidate,
    TrainingWorkflow,
    TrainingWorkflowStatus,
)
from .projection import current_cash, exact_employee_training


def create_training_workflow(
    snapshot: GameSnapshot, candidate: TrainingCandidate, *, now: datetime | None = None
) -> TrainingWorkflow:
    if not candidate.eligible:
        raise SoftwareIncUIValidationError("an ineligible employee cannot start education")
    current = now or datetime.now(UTC)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "game_session_id": snapshot.game_session_id,
        "save_identity": save_identity,
        "employee_id": candidate.employee.employee_id,
        "role": candidate.employee.role,
        "specialization": candidate.employee.specialization,
        "requested_months": candidate.requested_months,
        "course_duration_months": candidate.course_duration_months,
        "projected_cost": str(candidate.projected_direct_cost),
        "reserve": str(candidate.minimum_cash_reserve),
        "initial_level": candidate.employee.level,
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    workflow_id = uuid5(NAMESPACE_URL, f"sim-pilot:software-inc:training:{fingerprint}")
    workflow = TrainingWorkflow(
        workflow_id=workflow_id,
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        employee_id=candidate.employee.employee_id,
        employee_name=candidate.employee.employee_name,
        team_name=candidate.employee.team_name,
        completed_courses=0,
        projected_direct_cost=candidate.projected_direct_cost,
        actual_direct_cost=Decimal("0"),
        payroll_during_training=candidate.payroll_during_training,
        minimum_cash_reserve=candidate.minimum_cash_reserve,
        initial_cash=candidate.observed_cash,
        initial_level=candidate.employee.level,
        current_level=candidate.employee.level,
        status=TrainingWorkflowStatus.WAITING_FOR_APPROVAL,
        plan_fingerprint=fingerprint,
        last_bridge_sequence=snapshot.bridge_sequence,
        created_at=current,
        updated_at=current,
    )
    approval = TrainingApproval(
        approval_id=uuid4(),
        workflow_id=workflow_id,
        action_summary=(
            f"Educate {candidate.employee.employee_name!r} from {candidate.employee.team_name} "
            "in Designer/System for course 1 of 3 (one in-game month), level "
            f"{candidate.employee.level} -> {candidate.employee.level + 1}; exact direct cost "
            f"${candidate.current_course_cost:,.2f}, one-month continuing payroll "
            f"${candidate.employee.monthly_salary:,.2f}, cash after this course "
            f"${candidate.observed_cash - candidate.current_course_cost:,.2f}, required reserve "
            f"${candidate.minimum_cash_reserve:,.2f}. The full three-course curriculum is "
            f"projected to cost ${candidate.projected_direct_cost:,.2f}; later courses require "
            "fresh approval."
        ),
        employee_id=candidate.employee.employee_id,
        employee_name=candidate.employee.employee_name,
        team_name=candidate.employee.team_name,
        stage_number=1,
        level_before=candidate.employee.level,
        level_after=candidate.employee.level + 1,
        direct_cost=candidate.current_course_cost,
        payroll_during_training=candidate.employee.monthly_salary,
        cash_after_direct_cost=candidate.observed_cash - candidate.current_course_cost,
        minimum_cash_reserve=candidate.minimum_cash_reserve,
        plan_fingerprint=fingerprint,
        created_at=current,
    )
    return workflow.model_copy(update={"pending_approval": approval})


def resolve_training_approval(
    workflow: TrainingWorkflow, *, approved: bool, now: datetime | None = None
) -> TrainingWorkflow:
    approval = workflow.pending_approval
    if approval is None or approval.approved is not None:
        raise SoftwareIncUIValidationError("education workflow has no pending approval")
    current = now or datetime.now(UTC)
    return workflow.model_copy(
        update={
            "pending_approval": approval.model_copy(
                update={"approved": approved, "resolved_at": current}
            ),
            "status": TrainingWorkflowStatus.PLANNED
            if approved
            else TrainingWorkflowStatus.BLOCKED,
            "updated_at": current,
        }
    )


def synchronize_training(
    workflow: TrainingWorkflow, snapshot: GameSnapshot, *, now: datetime | None = None
) -> TrainingWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if (
        workflow.game_session_id != snapshot.game_session_id
        or workflow.save_identity != save_identity
    ):
        raise SoftwareIncUIValidationError("education workflow save or session identity is stale")
    if snapshot.bridge_sequence <= workflow.last_bridge_sequence:
        raise SoftwareIncUIValidationError("education workflow requires a fresh bridge sequence")
    employee = exact_employee_training(
        snapshot, employee_id=workflow.employee_id, role="Designer", specialization="System"
    )
    course_active = any(
        course.casefold() == "designer:system" for course in employee.active_courses
    )
    status = workflow.status
    completed_courses = workflow.completed_courses
    pending_approval = workflow.pending_approval
    started = workflow.started_at_game_time
    completed = workflow.completed_at_game_time
    game_time = snapshot.game_state.get("current_time")
    observed_time = game_time if isinstance(game_time, str) else None
    if course_active:
        status = TrainingWorkflowStatus.ACTIVE
        started = started or observed_time
    elif workflow.status is TrainingWorkflowStatus.ACTIVE:
        expected_level = workflow.initial_level + workflow.completed_courses + 1
        if employee.level != expected_level:
            raise SoftwareIncUIValidationError(
                "education course disappeared without exactly one approved specialization gain"
            )
        completed_courses += 1
        if employee.level >= workflow.target_level:
            status = TrainingWorkflowStatus.COMPLETED
            completed = observed_time
            pending_approval = None
        else:
            status = TrainingWorkflowStatus.WAITING_FOR_APPROVAL
            pending_approval = _next_stage_approval(
                workflow,
                employee_level=employee.level,
                direct_cost=employee.one_time_cost,
                cash=current_cash(snapshot),
                stage_number=completed_courses + 1,
                now=now or datetime.now(UTC),
            )
    return workflow.model_copy(
        update={
            "completed_courses": completed_courses,
            "completed_at_game_time": completed,
            "current_level": employee.level,
            "last_bridge_sequence": snapshot.bridge_sequence,
            "pending_approval": pending_approval,
            "started_at_game_time": started,
            "status": status,
            "updated_at": now or datetime.now(UTC),
        }
    )


def _next_stage_approval(
    workflow: TrainingWorkflow,
    *,
    employee_level: int,
    direct_cost: Decimal,
    cash: Decimal,
    stage_number: int,
    now: datetime,
) -> TrainingApproval:
    payroll = workflow.payroll_during_training / workflow.requested_months
    cash_after = cash - direct_cost
    if cash_after < workflow.minimum_cash_reserve:
        raise SoftwareIncUIValidationError(
            "next education course would violate the persisted cash reserve"
        )
    return TrainingApproval(
        approval_id=uuid4(),
        workflow_id=workflow.workflow_id,
        action_summary=(
            f"Continue {workflow.employee_name!r} in Designer/System with course "
            f"{stage_number} of 3 (one in-game month), level {employee_level} -> "
            f"{employee_level + 1}; exact direct cost ${direct_cost:,.2f}, one-month "
            f"continuing payroll ${payroll:,.2f}, cash after this course "
            f"${cash_after:,.2f}, required reserve ${workflow.minimum_cash_reserve:,.2f}."
        ),
        employee_id=workflow.employee_id,
        employee_name=workflow.employee_name,
        team_name=workflow.team_name,
        stage_number=stage_number,
        level_before=employee_level,
        level_after=employee_level + 1,
        direct_cost=direct_cost,
        payroll_during_training=payroll,
        cash_after_direct_cost=cash_after,
        minimum_cash_reserve=workflow.minimum_cash_reserve,
        plan_fingerprint=workflow.plan_fingerprint,
        created_at=now,
    )


__all__ = [
    "create_training_workflow",
    "resolve_training_approval",
    "synchronize_training",
]
