"""Typed Prompt 6A contract planning and workflow contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContractStage(StrEnum):
    AVAILABLE = "available"
    DESIGN = "design"
    DEVELOPMENT = "development"
    ALPHA = "alpha"
    BETA = "beta"
    RELEASED = "released"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ContractCommitment(StrEnum):
    ACCEPT = "accept"
    DEADLINE_RISK = "deadline_risk"
    REVIEW = "review"
    PROMOTE = "promote"
    RELEASE = "release"


class ContractWorkflowStatus(StrEnum):
    PLANNED = "planned"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class ContractObservation(ContractModel):
    contract_id: str = Field(min_length=1, max_length=512)
    display_index: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=256)
    client: str = Field(min_length=1, max_length=256)
    software_type: str = Field(min_length=1, max_length=256)
    software_category: str
    features: tuple[str, ...]
    months: int = Field(ge=0)
    development_time: Decimal = Field(ge=0)
    difficulty: Decimal = Field(ge=0)
    art_ratio: Decimal = Field(ge=0)
    minimum_progress: Decimal = Field(ge=0)
    quality_target: Decimal = Field(ge=0)
    reward: Decimal = Field(ge=0)
    penalty: Decimal = Field(ge=0)
    per_bug_penalty: Decimal = Field(ge=0)
    deadline: str = Field(min_length=1)
    days_remaining: Decimal
    game_status: str


class ContractWorkObservation(ContractModel):
    work_item_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    contract_name: str = Field(min_length=1)
    client: str
    deadline: str
    deadline_observed: bool | None = None
    days_remaining: Decimal
    contract_started: bool | None = None
    reward: Decimal = Field(ge=0)
    penalty: Decimal = Field(ge=0)
    stage: ContractStage
    stage_text: str
    progress: Decimal = Field(ge=0)
    minimum_progress: Decimal = Field(ge=0)
    assigned_teams: tuple[str, ...]
    employee_count: int = Field(ge=0)
    paused: bool
    done: bool
    bugs: Decimal | None = Field(default=None, ge=0)
    fixed_bugs: Decimal | None = Field(default=None, ge=0)
    quality: Decimal | None = Field(default=None, ge=0)
    review_score: Decimal | None = Field(default=None, ge=0)
    reviews_done: int | None = Field(default=None, ge=0)
    in_beta: bool | None = None
    released: bool | None = None

    @model_validator(mode="after")
    def validate_deadline_observation(self) -> ContractWorkObservation:
        if self.deadline_observed is True and not self.deadline.strip():
            raise ValueError("an observed contract deadline requires its exact label")
        if self.deadline_observed is False and (self.deadline.strip() or self.days_remaining != 0):
            raise ValueError(
                "an unavailable contract deadline must have empty text and zero remaining days"
            )
        return self


class TeamContractAssessment(ContractModel):
    team_id: str
    team_name: str
    employee_count: int = Field(ge=0)
    required_roles: tuple[str, ...]
    observed_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]
    active_work_items: tuple[str, ...]
    current_workspace_capacity: int | None = Field(default=None, ge=0)
    required_workspace_capacity: int = Field(ge=0)
    conservative_required_days: Decimal = Field(ge=0)
    deadline_buffer_days: Decimal
    suitable: bool
    reasons: tuple[str, ...]


class ContractCandidate(ContractModel):
    contract: ContractObservation
    team: TeamContractAssessment
    observed_cash: Decimal
    worst_case_cash_after_penalty: Decimal
    minimum_reward: Decimal = Field(ge=0)
    minimum_cash_reserve: Decimal = Field(ge=0)
    eligible: bool
    reasons: tuple[str, ...]


class ContractRecommendation(ContractModel):
    schema_version: Literal[1] = 1
    recommendation_id: str = Field(pattern=r"^contract-recommendation:[0-9a-f]{24}$")
    game_session_id: str
    save_identity: str
    source_bridge_sequence: int = Field(ge=1)
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommended: ContractCandidate | None
    alternatives: tuple[ContractCandidate, ...] = Field(max_length=2)
    rejected_count: int = Field(ge=0)
    rejection_reasons: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_expiry(self) -> ContractRecommendation:
        if self.expires_at <= self.created_at:
            raise ValueError("recommendation expiration must follow creation")
        if self.recommended is not None and not self.recommended.eligible:
            raise ValueError("recommended contract must be eligible")
        return self


class ContractApproval(ContractModel):
    schema_version: Literal[1] = 1
    approval_id: UUID
    workflow_id: UUID
    commitment: ContractCommitment
    action_summary: str = Field(min_length=1, max_length=1024)
    contract_id: str
    team_name: str
    reward: Decimal = Field(ge=0)
    maximum_penalty: Decimal = Field(ge=0)
    one_time_cost: Decimal = Field(default=Decimal("0"), ge=0)
    configuration: str | None = Field(default=None, min_length=1, max_length=512)
    deadline: str
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool | None = None
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> ContractApproval:
        if (self.approved is None) != (self.resolved_at is None):
            raise ValueError("pending approval cannot be resolved; resolution requires a decision")
        is_review = self.commitment is ContractCommitment.REVIEW
        if is_review != (self.configuration is not None):
            raise ValueError("review approval requires the exact observed configuration")
        if not is_review and self.one_time_cost != 0:
            raise ValueError("only a review approval may carry a one-time cost")
        return self


class ContractWorkflow(ContractModel):
    schema_version: Literal[1] = 1
    workflow_id: UUID
    game_session_id: str
    save_identity: str
    contract_id: str
    contract_name: str
    client: str
    team_name: str
    minimum_reward: Decimal = Field(ge=0)
    minimum_cash_reserve: Decimal = Field(ge=0)
    reward: Decimal = Field(ge=0)
    maximum_penalty: Decimal = Field(ge=0)
    deadline: str
    status: ContractWorkflowStatus
    observed_stage: ContractStage
    work_item_id: str | None = None
    pending_approval: ContractApproval | None = None
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    last_bridge_sequence: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ContractCycleEvent(ContractModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    workflow_id: UUID
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=64)
    bridge_sequence: int = Field(ge=1)
    stage_before: ContractStage
    stage_after: ContractStage
    action: str | None = None
    input_sent: bool
    verified: bool
    detail: str = Field(min_length=1, max_length=2048)
    recorded_at: AwareDatetime


class ContractOperationResult(ContractModel):
    schema_version: Literal[1] = 1
    workflow: ContractWorkflow | None = None
    recommendation: ContractRecommendation | None = None
    event: ContractCycleEvent | None = None
    gestures_sent: int = Field(ge=0)
    verified: bool
    partial: bool
    message: str = Field(min_length=1, max_length=2048)
    completed_at: datetime


__all__ = [
    "ContractApproval",
    "ContractCandidate",
    "ContractCommitment",
    "ContractCycleEvent",
    "ContractObservation",
    "ContractOperationResult",
    "ContractRecommendation",
    "ContractStage",
    "ContractWorkObservation",
    "ContractWorkflow",
    "ContractWorkflowStatus",
    "TeamContractAssessment",
]
