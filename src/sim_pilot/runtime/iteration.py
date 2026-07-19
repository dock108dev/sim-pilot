"""One evaluate/decide/validate/execute/verify/commit runtime loop."""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sim_pilot.adapters.base import SimulationAdapter
from sim_pilot.domain import DecisionType, Observation, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import ApprovalRecord, TaskRecord
from sim_pilot.runtime.action_attempts import action_fingerprint
from sim_pilot.runtime.action_execution import (
    ActionExecutionState,
    execute_action_transaction,
)
from sim_pilot.runtime.decision_errors import DecisionProviderError
from sim_pilot.runtime.decisions import ScriptedDecisionExhaustedError
from sim_pilot.runtime.engine_support import (
    action_state_fingerprint,
    adapter_snapshot,
    observation_draft,
    with_status,
)
from sim_pilot.runtime.errors import DurablePersistenceError
from sim_pilot.runtime.execution_services import RuntimeExecutionServices
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.models import (
    ApprovalRequest,
    EvaluationStatus,
    RuntimeEventType,
    RuntimeSafeguardState,
)
from sim_pilot.runtime.persistence import EventDraft

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeLoopResult:
    current: TaskRecord
    runtime_state: RuntimeSafeguardState
    observation: Observation
    reason: str | None


async def run_iterations(
    services: RuntimeExecutionServices,
    current: TaskRecord,
    runtime_state: RuntimeSafeguardState,
    observation: Observation,
    adapter: SimulationAdapter,
    decision_provider: DecisionProvider,
    *,
    iteration_budget: int | None,
) -> RuntimeLoopResult:
    """Run committed iterations until the task yields or reaches a terminal state."""
    committed_this_run = 0
    reason: str | None = None
    active_action_id: UUID | None = None
    try:
        while current.task.status is TaskStatus.RUNNING:
            if iteration_budget is not None and committed_this_run >= iteration_budget:
                reason = "execution slice complete"
                break
            if current.cancel_requested or services.cancellation_check(current.task.id):
                cancelled = with_status(current.task, TaskStatus.CANCELLED)
                commit = services.persistence.commit_iteration(
                    current,
                    task=cancelled,
                    runtime_state=runtime_state,
                    cancel_requested=True,
                    event_drafts=(
                        EventDraft(
                            RuntimeEventType.TASK_CANCELLED,
                            {"reason": "cancellation requested"},
                        ),
                    ),
                    adapter_snapshot=adapter_snapshot(adapter, observation),
                )
                current = commit.task_record
                reason = "cancellation requested"
                break
            if runtime_state.iterations >= services.configuration.max_iterations:
                current, reason = services.commit_terminal(
                    current,
                    runtime_state,
                    adapter,
                    observation,
                    TaskStatus.BLOCKED,
                    "maximum iterations reached",
                    (
                        EventDraft(
                            RuntimeEventType.EVALUATION_RECORDED, {"safeguard": "iterations"}
                        ),
                    ),
                )
                break

            runtime_state = runtime_state.model_copy(
                update={"iterations": runtime_state.iterations + 1}
            )
            drafts: list[EventDraft] = []
            evaluation = services.evaluator.evaluate(
                current.task.specification,
                observation,
                observation_history=services.observation_history(current.task.id),
            )
            drafts.append(
                EventDraft(
                    RuntimeEventType.EVALUATION_RECORDED,
                    cast("dict[str, JsonValue]", evaluation.model_dump(mode="json")),
                )
            )
            if evaluation.current_status is EvaluationStatus.COMPLETED:
                drafts.append(
                    EventDraft(
                        RuntimeEventType.TASK_COMPLETED,
                        {"reason": evaluation.progress_summary},
                    )
                )
                current = services.commit_with_drafts(
                    current,
                    with_status(current.task, TaskStatus.COMPLETED),
                    runtime_state,
                    tuple(drafts),
                    adapter_snapshot(adapter, observation),
                )
                reason = evaluation.progress_summary
                break
            if evaluation.current_status is EvaluationStatus.BLOCKED:
                reason = evaluation.blocked_reason or evaluation.progress_summary
                drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                current = services.commit_with_drafts(
                    current,
                    with_status(current.task, TaskStatus.BLOCKED),
                    runtime_state,
                    tuple(drafts),
                    adapter_snapshot(adapter, observation),
                )
                break

            approved_action = runtime_state.approved_once_action
            decision = None
            if approved_action is None:
                try:
                    available_actions = await adapter.available_actions()
                    decision_context = services.decision_context_projector.project(
                        task=current.task,
                        observation=observation,
                        available_actions=available_actions,
                        events=services.event_store.list_events(current.task.id),
                        runtime_state=runtime_state,
                        progress=evaluation,
                    )
                    provider_result = await decision_provider.decide(decision_context)
                    decision = provider_result.decision
                except ScriptedDecisionExhaustedError as error:
                    reason = str(error)
                    drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                    current = services.commit_with_drafts(
                        current,
                        with_status(current.task, TaskStatus.BLOCKED),
                        runtime_state,
                        tuple(drafts),
                        adapter_snapshot(adapter, observation),
                    )
                    break
                except DecisionProviderError as error:
                    reason = str(error)
                    drafts.extend(
                        (
                            EventDraft(
                                RuntimeEventType.DECISION_PROVIDER_FAILED,
                                {
                                    "error_type": type(error).__name__,
                                    "reason": reason,
                                },
                            ),
                            EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}),
                        )
                    )
                    current = services.commit_with_drafts(
                        current,
                        with_status(current.task, TaskStatus.FAILED),
                        runtime_state,
                        tuple(drafts),
                        adapter_snapshot(adapter, observation),
                    )
                    break
                drafts.append(
                    EventDraft(
                        RuntimeEventType.DECISION_GENERATED,
                        {
                            **cast(
                                "dict[str, JsonValue]",
                                decision.model_dump(mode="json"),
                            ),
                            "provider_metadata": cast(
                                "dict[str, JsonValue]",
                                provider_result.metadata.model_dump(mode="json"),
                            ),
                        },
                    )
                )
                if decision.type is DecisionType.COMPLETE:
                    reason = "decision provider claimed completion before evaluator confirmation"
                    drafts.append(EventDraft(RuntimeEventType.ACTION_REJECTED, {"reason": reason}))
                    runtime_state = runtime_state.model_copy(
                        update={
                            "consecutive_failures": runtime_state.consecutive_failures + 1,
                            "rejected_action_count": runtime_state.rejected_action_count + 1,
                        }
                    )
                    if (
                        services.configuration.block_on_false_completion
                        or runtime_state.consecutive_failures
                        >= services.configuration.max_consecutive_failures
                    ):
                        drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                        task_next = with_status(current.task, TaskStatus.BLOCKED)
                        snapshot = adapter_snapshot(adapter, observation)
                    else:
                        task_next = current.task
                        snapshot = None
                    current = services.commit_with_drafts(
                        current, task_next, runtime_state, tuple(drafts), snapshot
                    )
                    committed_this_run += 1
                    if task_next.status is TaskStatus.BLOCKED:
                        break
                    continue
                if decision.type is DecisionType.BLOCKED:
                    reason = decision.reason
                    drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                    current = services.commit_with_drafts(
                        current,
                        with_status(current.task, TaskStatus.BLOCKED),
                        runtime_state,
                        tuple(drafts),
                        adapter_snapshot(adapter, observation),
                    )
                    break
                if decision.type is DecisionType.WAIT:
                    external_refresh = bool(
                        getattr(adapter, "requires_fresh_observation_on_resume", False)
                    )
                    if external_refresh:
                        observation = await adapter.observe()
                        drafts.append(observation_draft(observation))
                    state_fingerprint = json.dumps(
                        observation.state, sort_keys=True, separators=(",", ":")
                    )
                    repeated = (
                        runtime_state.repeated_state_count + 1
                        if state_fingerprint == runtime_state.last_state_fingerprint
                        else 1
                    )
                    runtime_state = runtime_state.model_copy(
                        update={
                            "repeated_state_count": repeated,
                            "last_state_fingerprint": state_fingerprint,
                        }
                    )
                    if repeated >= services.configuration.repeated_state_limit:
                        reason = "repeated state detected"
                        drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                        task_next = with_status(current.task, TaskStatus.BLOCKED)
                        snapshot = adapter_snapshot(adapter, observation)
                    else:
                        task_next = current.task
                        snapshot = (
                            adapter_snapshot(adapter, observation) if external_refresh else None
                        )
                    current = services.commit_with_drafts(
                        current, task_next, runtime_state, tuple(drafts), snapshot
                    )
                    committed_this_run += 1
                    if task_next.status is TaskStatus.BLOCKED:
                        break
                    continue
                if decision.action is None:
                    reason = "decision requiring execution did not contain an action"
                    drafts.append(EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}))
                    current = services.commit_with_drafts(
                        current,
                        with_status(current.task, TaskStatus.FAILED),
                        runtime_state,
                        tuple(drafts),
                        adapter_snapshot(adapter, observation),
                    )
                    break
                action = decision.action
            else:
                action = approved_action

            fingerprint = action_state_fingerprint(action, observation)
            repeated_action = (
                runtime_state.repeated_action_count
                if approved_action is not None
                else runtime_state.repeated_action_count + 1
                if fingerprint == runtime_state.last_action_fingerprint
                else 1
            )
            runtime_state = runtime_state.model_copy(
                update={
                    "last_action_fingerprint": fingerprint,
                    "repeated_action_count": repeated_action,
                }
            )
            if (
                approved_action is None
                and repeated_action >= services.configuration.repeated_action_limit
            ):
                reason = "repeated action detected"
                drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                current = services.commit_with_drafts(
                    current,
                    with_status(current.task, TaskStatus.BLOCKED),
                    runtime_state,
                    tuple(drafts),
                    adapter_snapshot(adapter, observation),
                )
                break

            adapter_validation = await adapter.validate(action)
            policy = services.policy.evaluate(
                current.task.specification,
                action,
                observation,
                current.task.total_spend,
                adapter_validation,
            )
            drafts.append(
                EventDraft(
                    RuntimeEventType.POLICY_VALIDATED,
                    cast("dict[str, JsonValue]", policy.model_dump(mode="json")),
                )
            )
            if not policy.allowed:
                reason = "; ".join(policy.reasons)
                drafts.append(
                    EventDraft(
                        RuntimeEventType.ACTION_REJECTED,
                        {
                            "reason": reason,
                            "action_type": action.type,
                            "action_fingerprint": action_fingerprint(action),
                        },
                    )
                )
                runtime_state = runtime_state.model_copy(
                    update={
                        "consecutive_failures": runtime_state.consecutive_failures + 1,
                        "rejected_action_count": runtime_state.rejected_action_count + 1,
                    }
                )
                stale = bool(getattr(adapter_validation, "state_stale", False))
                if stale:
                    observation = await adapter.observe()
                    drafts.append(observation_draft(observation))
                if (
                    runtime_state.consecutive_failures
                    >= services.configuration.max_consecutive_failures
                ):
                    drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                    task_next = with_status(current.task, TaskStatus.BLOCKED)
                    snapshot = adapter_snapshot(adapter, observation)
                else:
                    task_next = current.task
                    snapshot = adapter_snapshot(adapter, observation) if stale else None
                current = services.commit_with_drafts(
                    current, task_next, runtime_state, tuple(drafts), snapshot
                )
                committed_this_run += 1
                if task_next.status is TaskStatus.BLOCKED:
                    break
                continue

            was_approved = approved_action is not None
            approval_needed = policy.approval_required or (
                decision is not None and decision.type is DecisionType.APPROVAL_REQUIRED
            )
            if approval_needed and not was_approved:
                sequence = current.task.sequence + len(drafts) + 1
                request = ApprovalRequest(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"sim-pilot:{current.task.id}:approval:{sequence}",
                    ),
                    task_id=current.task.id,
                    action=action,
                    created_at=datetime.now(UTC),
                )
                drafts.append(
                    EventDraft(
                        RuntimeEventType.APPROVAL_REQUESTED,
                        {"approval_id": str(request.id), "action_type": action.type},
                    )
                )
                waiting = with_status(current.task, TaskStatus.WAITING_FOR_APPROVAL)
                commit = services.persistence.commit_iteration(
                    current,
                    task=waiting,
                    runtime_state=runtime_state,
                    event_drafts=tuple(drafts),
                    approval_create=ApprovalRecord(
                        approval=request,
                        reason="; ".join(policy.reasons) or "approval required",
                    ),
                )
                current = commit.task_record
                reason = "approval required"
                break

            action_state = ActionExecutionState(
                current=current,
                runtime_state=runtime_state,
                observation=observation,
                drafts=drafts,
            )
            try:
                await execute_action_transaction(
                    services,
                    action_state,
                    adapter,
                    action,
                    adapter_validation,
                )
            except BaseException:
                current = action_state.current
                runtime_state = action_state.runtime_state
                observation = action_state.observation
                reason = action_state.reason
                active_action_id = action_state.active_action_id
                raise
            current = action_state.current
            runtime_state = action_state.runtime_state
            observation = action_state.observation
            reason = action_state.reason
            active_action_id = action_state.active_action_id
            committed_this_run += 1
            if action_state.terminal_status is not None:
                break
    except DurablePersistenceError:
        raise
    except Exception as error:
        reason = f"runtime exception: {error}"
        logger.exception(
            "unexpected runtime failure task_id=%s phase=runtime_iteration error_type=%s",
            current.task.id,
            type(error).__name__,
        )
        if current.task.status is TaskStatus.RUNNING:
            failed = with_status(current.task, TaskStatus.FAILED)
            snapshot = adapter_snapshot(adapter, observation)
            failure_drafts = (
                (
                    EventDraft(
                        RuntimeEventType.ACTION_ATTEMPT_FAILED,
                        {"action_id": str(active_action_id), "reason": reason},
                    ),
                )
                if active_action_id is not None
                else ()
            )
            commit = services.persistence.commit_iteration(
                current,
                task=failed,
                runtime_state=runtime_state,
                event_drafts=(
                    *failure_drafts,
                    EventDraft(
                        RuntimeEventType.TASK_FAILED,
                        {
                            "reason": reason,
                            "error_type": type(error).__name__,
                            "phase": "runtime_iteration",
                        },
                    ),
                ),
                adapter_snapshot=snapshot,
            )
            current = commit.task_record

    return RuntimeLoopResult(
        current=current,
        runtime_state=runtime_state,
        observation=observation,
        reason=reason,
    )
