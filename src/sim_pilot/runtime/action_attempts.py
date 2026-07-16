"""Durable action-attempt state derived from the append-only event journal."""

import hashlib
import json
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, Field

from sim_pilot.domain import Action, Observation
from sim_pilot.runtime.errors import ReconstructionConsistencyError
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType, RuntimeModel


class ActionAttemptStatus(StrEnum):
    PREPARED = "prepared"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_CONFIRMED = "execution_confirmed"
    CHECKPOINT_COMMITTED = "checkpoint_committed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RECONCILED = "reconciled"
    FAILED = "failed"


class ReconciliationClassification(StrEnum):
    DEFINITELY_NOT_EXECUTED = "definitely_not_executed"
    DEFINITELY_EXECUTED = "definitely_executed"
    INFERABLE = "inferable"
    AMBIGUOUS = "ambiguous"
    ADAPTER_UNAVAILABLE = "adapter_unavailable"


class RecoveryResolution(StrEnum):
    ACCEPT_CURRENT = "accept_current"
    MARK_EXECUTED = "mark_executed"
    MARK_NOT_EXECUTED = "mark_not_executed"
    ABANDON = "abandon"
    RESTORE_PRIOR_CHECKPOINT = "restore_prior_checkpoint"


class ActionAttempt(RuntimeModel):
    """Current durable state of one external action attempt."""

    task_id: UUID
    runtime_sequence: int = Field(ge=1)
    action_id: UUID
    action_fingerprint: str = Field(min_length=1)
    action: Action
    prior_checkpoint_id: UUID | None
    prior_observation_fingerprint: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    estimated_cost: float = Field(ge=0)
    status: ActionAttemptStatus
    prepared_at: AwareDatetime
    updated_at: AwareDatetime
    classification: ReconciliationClassification | None = None
    reason: str | None = None


ATTEMPT_EVENT_STATUS = {
    RuntimeEventType.ACTION_PREPARED: ActionAttemptStatus.PREPARED,
    RuntimeEventType.ACTION_EXECUTION_STARTED: ActionAttemptStatus.EXECUTION_STARTED,
    RuntimeEventType.ACTION_EXECUTION_CONFIRMED: ActionAttemptStatus.EXECUTION_CONFIRMED,
    RuntimeEventType.ACTION_CHECKPOINT_COMMITTED: ActionAttemptStatus.CHECKPOINT_COMMITTED,
    RuntimeEventType.ACTION_RECONCILIATION_REQUIRED: ActionAttemptStatus.RECONCILIATION_REQUIRED,
    RuntimeEventType.ACTION_RECONCILED: ActionAttemptStatus.RECONCILED,
    RuntimeEventType.ACTION_ATTEMPT_FAILED: ActionAttemptStatus.FAILED,
}

ATTEMPT_TRANSITIONS: dict[ActionAttemptStatus, set[ActionAttemptStatus]] = {
    ActionAttemptStatus.PREPARED: {
        ActionAttemptStatus.EXECUTION_STARTED,
        ActionAttemptStatus.RECONCILED,
        ActionAttemptStatus.FAILED,
    },
    ActionAttemptStatus.EXECUTION_STARTED: {
        ActionAttemptStatus.EXECUTION_CONFIRMED,
        ActionAttemptStatus.RECONCILIATION_REQUIRED,
        ActionAttemptStatus.RECONCILED,
        ActionAttemptStatus.FAILED,
    },
    ActionAttemptStatus.EXECUTION_CONFIRMED: {ActionAttemptStatus.CHECKPOINT_COMMITTED},
    ActionAttemptStatus.RECONCILIATION_REQUIRED: {
        ActionAttemptStatus.RECONCILED,
        ActionAttemptStatus.FAILED,
    },
    ActionAttemptStatus.CHECKPOINT_COMMITTED: set(),
    ActionAttemptStatus.RECONCILED: set(),
    ActionAttemptStatus.FAILED: set(),
}


def canonical_fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def action_fingerprint(action: Action) -> str:
    return canonical_fingerprint(action.model_dump(mode="json"))


def observation_fingerprint(observation: Observation) -> str:
    return canonical_fingerprint(
        {"sequence": observation.sequence, "tick": observation.tick, "state": observation.state}
    )


def action_attempts(events: tuple[RuntimeEvent, ...]) -> tuple[ActionAttempt, ...]:
    """Reconstruct every attempt and reject malformed journal transitions."""
    attempts: dict[UUID, ActionAttempt] = {}
    order: list[UUID] = []
    for event in events:
        status = ATTEMPT_EVENT_STATUS.get(event.event_type)
        if status is None:
            continue
        raw_id = event.payload.get("action_id")
        if not isinstance(raw_id, str):
            raise ReconstructionConsistencyError("action-attempt event has no action_id")
        try:
            identifier = UUID(raw_id)
        except ValueError as error:
            raise ReconstructionConsistencyError("action-attempt action_id is invalid") from error
        if event.event_type is RuntimeEventType.ACTION_PREPARED:
            if identifier in attempts:
                raise ReconstructionConsistencyError("action attempt was prepared more than once")
            try:
                action = Action.model_validate_json(json.dumps(event.payload["action"]))
                checkpoint_value = event.payload.get("prior_checkpoint_id")
                estimated_cost = event.payload["estimated_cost"]
                if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, (int, float)):
                    raise ValueError("estimated_cost must be numeric")
                attempt = ActionAttempt(
                    task_id=event.task_id,
                    runtime_sequence=event.sequence,
                    action_id=identifier,
                    action_fingerprint=str(event.payload["action_fingerprint"]),
                    action=action,
                    prior_checkpoint_id=(
                        None if checkpoint_value is None else UUID(str(checkpoint_value))
                    ),
                    prior_observation_fingerprint=str(
                        event.payload["prior_observation_fingerprint"]
                    ),
                    expected_effect=str(event.payload["expected_effect"]),
                    estimated_cost=float(estimated_cost),
                    status=status,
                    prepared_at=event.timestamp,
                    updated_at=event.timestamp,
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ReconstructionConsistencyError(
                    f"invalid action-prepared payload: {error}"
                ) from error
            attempts[identifier] = attempt
            order.append(identifier)
            continue
        attempt = attempts.get(identifier)
        if attempt is None:
            raise ReconstructionConsistencyError("action-attempt event precedes preparation")
        if status not in ATTEMPT_TRANSITIONS[attempt.status]:
            raise ReconstructionConsistencyError(
                f"invalid action-attempt transition: {attempt.status.value} -> {status.value}"
            )
        classification_value = event.payload.get("classification")
        try:
            classification = (
                attempt.classification
                if classification_value is None
                else ReconciliationClassification(str(classification_value))
            )
        except ValueError as error:
            raise ReconstructionConsistencyError(
                "action-attempt reconciliation classification is invalid"
            ) from error
        reason_value = event.payload.get("reason")
        attempts[identifier] = attempt.model_copy(
            update={
                "status": status,
                "updated_at": event.timestamp,
                "classification": classification,
                "reason": reason_value if isinstance(reason_value, str) else attempt.reason,
            }
        )
    return tuple(attempts[identifier] for identifier in order)


def unresolved_action_attempt(events: tuple[RuntimeEvent, ...]) -> ActionAttempt | None:
    attempts = action_attempts(events)
    if not attempts:
        return None
    latest = attempts[-1]
    if latest.status in {
        ActionAttemptStatus.CHECKPOINT_COMMITTED,
        ActionAttemptStatus.RECONCILED,
        ActionAttemptStatus.FAILED,
    }:
        return None
    return latest
