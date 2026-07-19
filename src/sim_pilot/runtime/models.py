"""Strict runtime-local orchestration models."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.domain import Action, TaskStatus
from sim_pilot.domain.models import JsonValue


class RuntimeModel(BaseModel):
    """Strict, versioned base for runtime data."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class EvaluationStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class RuntimeEvaluation(RuntimeModel):
    current_status: EvaluationStatus
    complete: bool
    progress_summary: str = Field(min_length=1)
    stop_condition_met: bool = False
    blocked_reason: str | None = None


class PolicyDecision(RuntimeModel):
    allowed: bool
    approval_required: bool = False
    reasons: tuple[str, ...] = ()


class VerificationResult(RuntimeModel):
    verified: bool
    reasons: tuple[str, ...] = ()


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ApprovalRequest(RuntimeModel):
    id: UUID
    task_id: UUID
    action: Action
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None


class RuntimeConfiguration(RuntimeModel):
    max_iterations: int = Field(default=100, gt=0)
    max_consecutive_failures: int = Field(default=3, gt=0)
    repeated_action_limit: int = Field(default=3, gt=1)
    repeated_state_limit: int = Field(default=3, gt=1)
    block_on_false_completion: bool = False
    decision_context_event_limit: int = Field(default=20, ge=0)
    decision_context_max_bytes: int = Field(default=65_536, gt=0)


class RuntimeSafeguardState(RuntimeModel):
    """Minimal durable state needed to preserve safeguards across restart."""

    iterations: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    repeated_action_count: int = Field(default=0, ge=0)
    repeated_state_count: int = Field(default=0, ge=0)
    rejected_action_count: int = Field(default=0, ge=0)
    last_action_fingerprint: str | None = None
    last_state_fingerprint: str | None = None
    approved_once_action: Action | None = None
    approved_approval_id: UUID | None = None


class RuntimeEventType(StrEnum):
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    OBSERVATION_RECORDED = "observation_recorded"
    EVALUATION_RECORDED = "evaluation_recorded"
    DECISION_GENERATED = "decision_generated"
    DECISION_PROVIDER_FAILED = "decision_provider_failed"
    POLICY_VALIDATED = "policy_validated"
    ACTION_PREPARED = "action_prepared"
    ACTION_EXECUTION_STARTED = "action_execution_started"
    ACTION_EXECUTION_CONFIRMED = "action_execution_confirmed"
    ACTION_CHECKPOINT_COMMITTED = "action_checkpoint_committed"
    ACTION_RECONCILIATION_REQUIRED = "action_reconciliation_required"
    ACTION_RECONCILED = "action_reconciled"
    ACTION_ATTEMPT_FAILED = "action_attempt_failed"
    ACTION_EXECUTED = "action_executed"
    ACTION_REJECTED = "action_rejected"
    VERIFICATION_RECORDED = "verification_recorded"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


class RuntimeEvent(RuntimeModel):
    task_id: UUID
    sequence: int = Field(ge=1)
    event_type: RuntimeEventType
    timestamp: AwareDatetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class RuntimeOutcome(RuntimeModel):
    task_id: UUID
    status: TaskStatus
    total_spend: float = Field(ge=0)
    iterations: int = Field(ge=0)
    reason: str | None = None
    pending_approval: ApprovalRequest | None = None


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    from datetime import UTC

    return datetime.now(UTC)
