"""Strict bounded context projected for one runtime decision request."""

import json
from contextlib import suppress
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.adapters.base import ActionDefinition
from sim_pilot.domain import (
    Action,
    ConstraintType,
    Decision,
    ExecutionResult,
    Observation,
    Task,
    TaskSpecification,
)
from sim_pilot.domain.models import JsonValue
from sim_pilot.provider_metadata import ProviderMetadata
from sim_pilot.runtime.decision_errors import DecisionContextTooLargeError
from sim_pilot.runtime.models import (
    RuntimeEvaluation,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeSafeguardState,
    VerificationResult,
)


class DecisionContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class DecisionEventSummary(DecisionContextModel):
    sequence: int = Field(ge=1)
    event_type: RuntimeEventType
    timestamp: AwareDatetime
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AuthoritySummary(DecisionContextModel):
    maximum_single_spend: Decimal | None = Field(default=None, ge=0)
    maximum_total_spend: Decimal | None = Field(default=None, ge=0)
    remaining_total_spend: Decimal | None = Field(default=None, ge=0)
    approval_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()


class PendingRestrictions(DecisionContextModel):
    forbidden_actions: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    rejected_actions: tuple[str, ...] = ()
    denied_actions: tuple[str, ...] = ()
    recent_failed_strategies: tuple[str, ...] = ()


class ExecutionSummary(DecisionContextModel):
    action: Action
    result: ExecutionResult | None = None
    verification: VerificationResult | None = None


class SafeguardSummary(DecisionContextModel):
    iterations: int = Field(ge=0)
    consecutive_failures: int = Field(ge=0)
    repeated_action_count: int = Field(ge=0)
    repeated_state_count: int = Field(ge=0)
    rejected_action_count: int = Field(ge=0)
    last_action_fingerprint: str | None = None


class DecisionContext(DecisionContextModel):
    task_id: UUID
    specification: TaskSpecification
    observation: Observation
    previous_observation: Observation | None = None
    available_actions: tuple[ActionDefinition, ...]
    recent_events: tuple[DecisionEventSummary, ...] = ()
    accumulated_spend: Decimal = Field(ge=0)
    remaining_authority: AuthoritySummary
    pending_restrictions: PendingRestrictions
    previous_execution: ExecutionSummary | None = None
    safeguards: SafeguardSummary
    progress: RuntimeEvaluation

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )


class DecisionProviderResult(DecisionContextModel):
    decision: Decision
    metadata: ProviderMetadata


RELEVANT_EVENT_TYPES = frozenset(
    {
        RuntimeEventType.DECISION_GENERATED,
        RuntimeEventType.POLICY_VALIDATED,
        RuntimeEventType.ACTION_PREPARED,
        RuntimeEventType.ACTION_EXECUTED,
        RuntimeEventType.ACTION_REJECTED,
        RuntimeEventType.VERIFICATION_RECORDED,
        RuntimeEventType.APPROVAL_REQUESTED,
        RuntimeEventType.APPROVAL_GRANTED,
        RuntimeEventType.APPROVAL_DENIED,
        RuntimeEventType.ACTION_ATTEMPT_FAILED,
        RuntimeEventType.ACTION_RECONCILIATION_REQUIRED,
        RuntimeEventType.ACTION_RECONCILED,
    }
)


class DecisionContextProjector:
    """Build deterministic provider input without exposing repositories."""

    def __init__(self, *, max_recent_events: int = 20, max_serialized_bytes: int = 65_536) -> None:
        if max_recent_events < 0 or max_serialized_bytes <= 0:
            raise ValueError("decision context limits must be positive")
        self.max_recent_events = max_recent_events
        self.max_serialized_bytes = max_serialized_bytes

    def project(
        self,
        *,
        task: Task,
        observation: Observation,
        available_actions: list[ActionDefinition],
        events: tuple[RuntimeEvent, ...],
        runtime_state: RuntimeSafeguardState,
        progress: RuntimeEvaluation,
    ) -> DecisionContext:
        relevant = tuple(event for event in events if event.event_type in RELEVANT_EVENT_TYPES)
        summaries = tuple(
            DecisionEventSummary(
                sequence=event.sequence,
                event_type=event.event_type,
                timestamp=event.timestamp,
                details=event.payload,
            )
            for event in relevant[-self.max_recent_events :]
        )
        previous_observation = self._previous_observation(events, observation.sequence)
        restrictions = self._restrictions(task, relevant)
        context = self._context(
            task,
            observation,
            previous_observation,
            available_actions,
            summaries,
            runtime_state,
            progress,
            restrictions,
            self._previous_execution(events),
        )
        while summaries and len(context.canonical_json().encode()) > self.max_serialized_bytes:
            summaries = summaries[1:]
            context = context.model_copy(update={"recent_events": summaries})
        if len(context.canonical_json().encode()) > self.max_serialized_bytes:
            raise DecisionContextTooLargeError(
                f"decision context exceeds {self.max_serialized_bytes} bytes"
            )
        return context

    @staticmethod
    def _context(
        task: Task,
        observation: Observation,
        previous_observation: Observation | None,
        available_actions: list[ActionDefinition],
        summaries: tuple[DecisionEventSummary, ...],
        runtime_state: RuntimeSafeguardState,
        progress: RuntimeEvaluation,
        restrictions: PendingRestrictions,
        previous_execution: ExecutionSummary | None,
    ) -> DecisionContext:
        authority = task.specification.authority
        remaining = (
            None
            if authority.maximum_total_spend is None
            else max(Decimal(0), authority.maximum_total_spend - task.total_spend)
        )
        return DecisionContext(
            task_id=task.id,
            specification=task.specification,
            observation=observation,
            previous_observation=previous_observation,
            available_actions=tuple(available_actions),
            recent_events=summaries,
            accumulated_spend=task.total_spend,
            remaining_authority=AuthoritySummary(
                maximum_single_spend=authority.maximum_single_spend,
                maximum_total_spend=authority.maximum_total_spend,
                remaining_total_spend=remaining,
                approval_actions=authority.approval_actions,
                forbidden_actions=authority.forbidden_actions,
            ),
            pending_restrictions=restrictions,
            previous_execution=previous_execution,
            safeguards=SafeguardSummary(
                iterations=runtime_state.iterations,
                consecutive_failures=runtime_state.consecutive_failures,
                repeated_action_count=runtime_state.repeated_action_count,
                repeated_state_count=runtime_state.repeated_state_count,
                rejected_action_count=runtime_state.rejected_action_count,
                last_action_fingerprint=runtime_state.last_action_fingerprint,
            ),
            progress=progress,
        )

    @staticmethod
    def _previous_observation(
        events: tuple[RuntimeEvent, ...], current_sequence: int
    ) -> Observation | None:
        for event in reversed(events):
            if event.event_type is not RuntimeEventType.OBSERVATION_RECORDED:
                continue
            try:
                candidate = Observation.model_validate_json(json.dumps(event.payload))
            except ValueError:
                continue
            if candidate.sequence < current_sequence:
                return candidate
        return None

    @staticmethod
    def _restrictions(task: Task, events: tuple[RuntimeEvent, ...]) -> PendingRestrictions:
        forbidden = set(task.specification.authority.forbidden_actions)
        allowed: set[str] = set()
        for constraint in task.specification.constraints:
            if constraint.type is ConstraintType.FORBIDDEN_ACTION:
                value = constraint.parameters.get("action")
                if isinstance(value, str):
                    forbidden.add(value)
            if constraint.type is ConstraintType.ALLOWED_ACTION:
                value = constraint.parameters.get("action")
                values = constraint.parameters.get("actions")
                if isinstance(value, str):
                    allowed.add(value)
                if isinstance(values, list):
                    allowed.update(item for item in values if isinstance(item, str))
        rejected: list[str] = []
        denied: list[str] = []
        failed: list[str] = []
        approval_actions: dict[str, str] = {}
        for event in events:
            if event.event_type is RuntimeEventType.APPROVAL_REQUESTED:
                approval_id = event.payload.get("approval_id")
                action_type = event.payload.get("action_type")
                if isinstance(approval_id, str) and isinstance(action_type, str):
                    approval_actions[approval_id] = action_type
            elif event.event_type is RuntimeEventType.APPROVAL_DENIED:
                approval_id = event.payload.get("approval_id")
                if isinstance(approval_id, str) and approval_id in approval_actions:
                    denied.append(approval_actions[approval_id])
            elif event.event_type is RuntimeEventType.ACTION_REJECTED:
                action_type = event.payload.get("action_type")
                reason = event.payload.get("reason")
                if isinstance(action_type, str):
                    rejected.append(action_type)
                elif isinstance(reason, str):
                    rejected.append(reason)
            elif event.event_type is RuntimeEventType.ACTION_ATTEMPT_FAILED:
                reason = event.payload.get("reason")
                if isinstance(reason, str):
                    failed.append(reason)
        return PendingRestrictions(
            forbidden_actions=tuple(sorted(forbidden)),
            allowed_actions=tuple(sorted(allowed)),
            rejected_actions=tuple(rejected[-5:]),
            denied_actions=tuple(denied[-5:]),
            recent_failed_strategies=tuple(failed[-5:]),
        )

    @staticmethod
    def _previous_execution(events: tuple[RuntimeEvent, ...]) -> ExecutionSummary | None:
        result: ExecutionResult | None = None
        verification: VerificationResult | None = None
        for event in reversed(events):
            if result is None and event.event_type is RuntimeEventType.ACTION_EXECUTED:
                with suppress(ValueError):
                    result = ExecutionResult.model_validate_json(json.dumps(event.payload))
            elif (
                verification is None and event.event_type is RuntimeEventType.VERIFICATION_RECORDED
            ):
                with suppress(ValueError):
                    verification = VerificationResult.model_validate_json(json.dumps(event.payload))
            elif event.event_type is RuntimeEventType.ACTION_PREPARED:
                raw_action = event.payload.get("action")
                if isinstance(raw_action, dict):
                    try:
                        action = Action.model_validate_json(json.dumps(raw_action))
                    except ValueError:
                        return None
                    return ExecutionSummary(
                        action=action,
                        result=result,
                        verification=verification,
                    )
        return None
