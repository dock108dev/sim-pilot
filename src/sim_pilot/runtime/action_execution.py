"""Crash-aware execution and verification of one validated action."""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sim_pilot.adapters.base import AdapterValidation, SimulationAdapter
from sim_pilot.domain import Action, Observation, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import TaskRecord
from sim_pilot.runtime.action_attempts import action_fingerprint, observation_fingerprint
from sim_pilot.runtime.engine_support import adapter_snapshot, observation_draft, with_status
from sim_pilot.runtime.execution_services import RuntimeExecutionServices
from sim_pilot.runtime.models import RuntimeEventType, RuntimeSafeguardState
from sim_pilot.runtime.persistence import EventDraft
from sim_pilot.runtime.recovery import CrashPoint


@dataclass
class ActionExecutionState:
    """Mutable state preserved even when execution raises between crash boundaries."""

    current: TaskRecord
    runtime_state: RuntimeSafeguardState
    observation: Observation
    drafts: list[EventDraft]
    reason: str | None = None
    active_action_id: UUID | None = None
    terminal_status: TaskStatus | None = None


async def execute_action_transaction(
    services: RuntimeExecutionServices,
    state: ActionExecutionState,
    adapter: SimulationAdapter,
    action: Action,
    adapter_validation: AdapterValidation,
) -> None:
    """Journal, execute, verify, and atomically checkpoint one action."""
    before = state.observation
    latest_checkpoint = services.reconstruct(state.current.task.id).checkpoint
    attempt_sequence = state.current.task.sequence + len(state.drafts) + 1
    action_id = uuid5(
        NAMESPACE_URL,
        f"sim-pilot:{state.current.task.id}:action-attempt:{attempt_sequence}",
    )
    state.active_action_id = action_id
    state.drafts.append(
        EventDraft(
            RuntimeEventType.ACTION_PREPARED,
            {
                "action_id": str(action_id),
                "action_fingerprint": action_fingerprint(action),
                "action": cast("dict[str, JsonValue]", action.model_dump(mode="json")),
                "prior_checkpoint_id": (
                    None if latest_checkpoint is None else str(latest_checkpoint.metadata.id)
                ),
                "prior_observation_fingerprint": observation_fingerprint(before),
                "expected_effect": action.expected_effect,
                "estimated_cost": float(adapter_validation.estimated_cost),
            },
        )
    )
    state.current = services.commit_with_drafts(
        state.current, state.current.task, state.runtime_state, tuple(state.drafts), None
    )
    state.drafts = []
    services.crash(CrashPoint.AFTER_PREPARED)
    state.current = services.commit_with_drafts(
        state.current,
        state.current.task,
        state.runtime_state,
        (
            EventDraft(
                RuntimeEventType.ACTION_EXECUTION_STARTED,
                {"action_id": str(action_id)},
            ),
        ),
        None,
    )
    services.crash(CrashPoint.BEFORE_EXECUTION)
    result = await adapter.execute(action)
    services.crash(CrashPoint.AFTER_EXECUTION)
    state.drafts.append(
        EventDraft(
            RuntimeEventType.ACTION_EXECUTED,
            cast("dict[str, JsonValue]", result.model_dump(mode="json")),
        )
    )
    state.observation = await adapter.observe()
    services.crash(CrashPoint.AFTER_OBSERVATION)
    state.drafts.append(observation_draft(state.observation))
    verification = services.verifier.verify(
        before,
        action,
        result,
        state.observation,
        adapter_validation.estimated_cost,
    )
    state.drafts.append(
        EventDraft(
            RuntimeEventType.VERIFICATION_RECORDED,
            cast("dict[str, JsonValue]", verification.model_dump(mode="json")),
        )
    )
    services.crash(CrashPoint.AFTER_VERIFICATION)
    state.runtime_state = state.runtime_state.model_copy(
        update={"approved_once_action": None, "approved_approval_id": None}
    )
    task_next = state.current.task
    state.terminal_status = None
    if not verification.verified:
        state.reason = "; ".join(verification.reasons)
        state.terminal_status = TaskStatus.FAILED
    elif not result.success:
        failures = state.runtime_state.consecutive_failures + 1
        state.runtime_state = state.runtime_state.model_copy(
            update={"consecutive_failures": failures}
        )
        if failures >= services.configuration.max_consecutive_failures:
            state.reason = result.message
            state.terminal_status = TaskStatus.BLOCKED
    else:
        state.runtime_state = state.runtime_state.model_copy(update={"consecutive_failures": 0})
        task_next = state.current.task.model_copy(
            update={
                "total_spend": state.current.task.total_spend + Decimal(str(result.cost)),
            }
        )

    state_fingerprint = json.dumps(state.observation.state, sort_keys=True, separators=(",", ":"))
    repeated_state = (
        state.runtime_state.repeated_state_count + 1
        if state_fingerprint == state.runtime_state.last_state_fingerprint
        else 1
    )
    state.runtime_state = state.runtime_state.model_copy(
        update={
            "last_state_fingerprint": state_fingerprint,
            "repeated_state_count": repeated_state,
        }
    )
    if (
        state.terminal_status is None
        and repeated_state >= services.configuration.repeated_state_limit
    ):
        state.reason = "repeated state detected"
        state.terminal_status = TaskStatus.BLOCKED
    if state.terminal_status is None and state.observation.state.get("failed") is True:
        state.reason = "simulation entered terminal failure"
        state.terminal_status = TaskStatus.FAILED
    terminal_draft: EventDraft | None = None
    if state.terminal_status is not None:
        task_next = with_status(task_next, state.terminal_status)
        event_type = {
            TaskStatus.BLOCKED: RuntimeEventType.TASK_BLOCKED,
            TaskStatus.FAILED: RuntimeEventType.TASK_FAILED,
        }[state.terminal_status]
        terminal_draft = EventDraft(event_type, {"reason": cast("str", state.reason)})
    state.drafts.append(
        EventDraft(
            RuntimeEventType.ACTION_EXECUTION_CONFIRMED,
            {
                "action_id": str(action_id),
                "success": result.success,
                "verified": verification.verified,
            },
        )
    )
    state.drafts.append(
        EventDraft(
            RuntimeEventType.ACTION_CHECKPOINT_COMMITTED,
            {"action_id": str(action_id)},
        )
    )
    if terminal_draft is not None:
        state.drafts.append(terminal_draft)
    snapshot = (
        adapter_snapshot(adapter, state.observation)
        if result.state_changed or state.terminal_status is not None
        else None
    )
    state.current = services.commit_with_drafts(
        state.current, task_next, state.runtime_state, tuple(state.drafts), snapshot
    )
    state.active_action_id = None
    services.crash(CrashPoint.AFTER_COMMIT)
    return
