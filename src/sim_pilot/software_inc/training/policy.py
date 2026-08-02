"""Deterministic advisor policy for one first education assignment."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import TrainingCandidate, TrainingRecommendation
from .projection import (
    assigned_active_work,
    current_cash,
    education_duration_months,
    team_employee_count,
    training_candidates,
)

_TTL = timedelta(minutes=3)
_MAXIMUM_SPECIALIZATION_LEVEL = 3
# Verified from Software Inc. 1.8.41 EducationWindow.EdCost. The current
# course price is still rebound to the live education surface before input.
_COURSE_COST_BY_LEVEL = (Decimal("600"), Decimal("2000"), Decimal("5000"))


def recommend_training(
    snapshot: GameSnapshot,
    *,
    team_name: str,
    minimum_cash_reserve: Decimal,
    requested_months: int = 3,
    now: datetime | None = None,
) -> TrainingRecommendation:
    if minimum_cash_reserve < 0:
        raise SoftwareIncUIValidationError("minimum cash reserve cannot be negative")
    duration = education_duration_months(snapshot)
    if requested_months != 3 or duration != 1:
        raise SoftwareIncUIValidationError(
            "this milestone requires three sequential one-month courses; "
            f"the game reports {duration} month(s) per course"
        )
    capacity = team_employee_count(snapshot, team_name)
    cash = current_cash(snapshot)
    displaced = assigned_active_work(snapshot, team_name)
    candidates: list[TrainingCandidate] = []
    for employee in training_candidates(
        snapshot, team_name=team_name, role="Designer", specialization="System"
    ):
        reasons: list[str] = []
        if employee.taking_courses or employee.active_courses:
            reasons.append("employee already has an active education assignment")
        target_level = employee.level + requested_months
        if target_level > _MAXIMUM_SPECIALIZATION_LEVEL:
            reasons.append(
                f"employee is already System level {employee.level}; three additional "
                f"one-month courses would exceed the maximum level "
                f"{_MAXIMUM_SPECIALIZATION_LEVEL}"
            )
        elif employee.one_time_cost != _COURSE_COST_BY_LEVEL[employee.level]:
            reasons.append(
                "live current-course price does not match the version-pinned cost schedule"
            )
        if displaced:
            reasons.append("current assigned work would be displaced: " + ", ".join(displaced))
        projected_cost = (
            sum(_COURSE_COST_BY_LEVEL[employee.level : target_level], Decimal("0"))
            if target_level <= _MAXIMUM_SPECIALIZATION_LEVEL
            else Decimal("0")
        )
        cash_after = cash - projected_cost
        if cash_after < minimum_cash_reserve:
            reasons.append(
                f"cash after ${projected_cost:,.2f} projected education cost would be "
                f"${cash_after:,.2f}, below the ${minimum_cash_reserve:,.2f} reserve"
            )
        candidates.append(
            TrainingCandidate(
                employee=employee,
                target_level=min(target_level, _MAXIMUM_SPECIALIZATION_LEVEL),
                current_course_cost=employee.one_time_cost,
                projected_direct_cost=projected_cost,
                payroll_during_training=employee.monthly_salary * requested_months,
                team_capacity_before=capacity,
                team_capacity_during=max(0, capacity - 1),
                observed_cash=cash,
                cash_after_projected_cost=cash_after,
                minimum_cash_reserve=minimum_cash_reserve,
                displaced_work=displaced,
                eligible=not reasons,
                reasons=tuple(reasons),
            )
        )
    eligible = sorted(
        (candidate for candidate in candidates if candidate.eligible),
        key=lambda candidate: (
            -candidate.employee.base_skill,
            candidate.employee.level,
            candidate.projected_direct_cost,
            candidate.employee.employee_id,
        ),
    )
    rejected = tuple(candidate for candidate in candidates if not candidate.eligible)
    created = now or datetime.now(UTC)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "adapter": snapshot.adapter_version,
        "game_session_id": snapshot.game_session_id,
        "save_identity": save_identity,
        "sequence": snapshot.bridge_sequence,
        "team": team_name,
        "reserve": str(minimum_cash_reserve),
        "duration": duration,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return TrainingRecommendation(
        recommendation_id=f"training-recommendation:{fingerprint[:24]}",
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        source_bridge_sequence=snapshot.bridge_sequence,
        capability_fingerprint=fingerprint,
        team_name=team_name,
        recommended=eligible[0] if eligible else None,
        alternatives=tuple(eligible[1:3]),
        rejected_count=len(rejected),
        rejection_reasons=tuple(sorted({reason for item in rejected for reason in item.reasons})),
        material_unknowns=(
            "The three-month objective is three sequential one-month courses in version 1.8.41; "
            "each later course receives a fresh exact approval.",
            "Payroll during education is an indirect continuing cost, not a new charge.",
            "The bridge proves public skill and specialization levels but does not predict the "
            "exact productivity gain of one level.",
        ),
        created_at=created,
        expires_at=created + _TTL,
    )


__all__ = ["recommend_training"]
