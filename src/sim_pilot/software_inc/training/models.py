"""Typed Prompt 6B education planning and workflow contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class TrainingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TrainingWorkflowStatus(StrEnum):
    PLANNED = "planned"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class EmployeeTrainingObservation(TrainingModel):
    employee_id: str
    employee_name: str
    team_name: str
    role: str
    specialization: str
    level: int = Field(ge=0)
    base_skill: Decimal = Field(ge=0)
    monthly_salary: Decimal = Field(ge=0)
    taking_courses: bool
    active_courses: tuple[str, ...]
    one_time_cost: Decimal = Field(ge=0)


class TrainingCandidate(TrainingModel):
    employee: EmployeeTrainingObservation
    requested_months: Literal[3] = 3
    course_duration_months: Literal[1] = 1
    planned_courses: Literal[3] = 3
    target_level: int = Field(ge=0, le=3)
    current_course_cost: Decimal = Field(ge=0)
    projected_direct_cost: Decimal = Field(ge=0)
    payroll_during_training: Decimal = Field(ge=0)
    team_capacity_before: int = Field(ge=0)
    team_capacity_during: int = Field(ge=0)
    observed_cash: Decimal
    cash_after_projected_cost: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    displaced_work: tuple[str, ...]
    eligible: bool
    reasons: tuple[str, ...]


class TrainingRecommendation(TrainingModel):
    schema_version: Literal[1] = 1
    recommendation_id: str = Field(pattern=r"^training-recommendation:[0-9a-f]{24}$")
    game_session_id: str
    save_identity: str
    source_bridge_sequence: int = Field(ge=1)
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_name: str
    role: Literal["Designer"] = "Designer"
    specialization: Literal["System"] = "System"
    requested_months: Literal[3] = 3
    recommended: TrainingCandidate | None
    alternatives: tuple[TrainingCandidate, ...] = Field(max_length=2)
    rejected_count: int = Field(ge=0)
    rejection_reasons: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_recommendation(self) -> TrainingRecommendation:
        if self.expires_at <= self.created_at:
            raise ValueError("recommendation expiration must follow creation")
        if self.recommended is not None and not self.recommended.eligible:
            raise ValueError("recommended education candidate must be eligible")
        return self


class TrainingApproval(TrainingModel):
    schema_version: Literal[1] = 1
    approval_id: UUID
    workflow_id: UUID
    action_summary: str = Field(min_length=1, max_length=1024)
    employee_id: str
    employee_name: str
    team_name: str
    role: Literal["Designer"] = "Designer"
    specialization: Literal["System"] = "System"
    course_duration_months: Literal[1] = 1
    stage_number: int = Field(ge=1, le=3)
    total_stages: Literal[3] = 3
    level_before: int = Field(ge=0, le=2)
    level_after: int = Field(ge=1, le=3)
    direct_cost: Decimal = Field(ge=0)
    payroll_during_training: Decimal = Field(ge=0)
    cash_after_direct_cost: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool | None = None
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> TrainingApproval:
        if (self.approved is None) != (self.resolved_at is None):
            raise ValueError("pending approval cannot be resolved; resolution requires a decision")
        return self


class TrainingWorkflow(TrainingModel):
    schema_version: Literal[1] = 1
    workflow_id: UUID
    game_session_id: str
    save_identity: str
    employee_id: str
    employee_name: str
    team_name: str
    role: Literal["Designer"] = "Designer"
    specialization: Literal["System"] = "System"
    requested_months: Literal[3] = 3
    course_duration_months: Literal[1] = 1
    target_level: Literal[3] = 3
    completed_courses: int = Field(ge=0, le=3)
    projected_direct_cost: Decimal = Field(ge=0)
    actual_direct_cost: Decimal = Field(ge=0)
    payroll_during_training: Decimal = Field(ge=0)
    minimum_cash_reserve: Decimal = Field(ge=0)
    initial_cash: Decimal
    initial_level: int = Field(ge=0)
    current_level: int = Field(ge=0)
    status: TrainingWorkflowStatus
    pending_approval: TrainingApproval | None = None
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at_game_time: str | None = None
    completed_at_game_time: str | None = None
    last_bridge_sequence: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TrainingCycleEvent(TrainingModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    workflow_id: UUID
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=64)
    bridge_sequence: int = Field(ge=1)
    action: str | None = None
    input_sent: bool
    verified: bool
    detail: str = Field(min_length=1, max_length=2048)
    recorded_at: AwareDatetime


class TrainingOperationResult(TrainingModel):
    schema_version: Literal[1] = 1
    workflow: TrainingWorkflow | None = None
    recommendation: TrainingRecommendation | None = None
    event: TrainingCycleEvent | None = None
    gestures_sent: int = Field(ge=0)
    verified: bool
    partial: bool
    message: str = Field(min_length=1, max_length=2048)
    completed_at: datetime


__all__ = [
    "EmployeeTrainingObservation",
    "TrainingApproval",
    "TrainingCandidate",
    "TrainingCycleEvent",
    "TrainingOperationResult",
    "TrainingRecommendation",
    "TrainingWorkflow",
    "TrainingWorkflowStatus",
]
