"""First complete deterministic runtime execution slice."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sim_pilot.adapters.base import SimulationAdapter
from sim_pilot.domain import Action, DecisionType, Observation, Task, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.runtime.decisions import ScriptedDecisionExhaustedError
from sim_pilot.runtime.evaluator import ProgressEvaluator
from sim_pilot.runtime.events import EventStore, InMemoryEventStore
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.lifecycle import transition
from sim_pilot.runtime.models import (
    ApprovalRequest,
    ApprovalStatus,
    EvaluationStatus,
    RuntimeConfiguration,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeOutcome,
)
from sim_pilot.runtime.policy import PolicyEngine
from sim_pilot.runtime.verification import ActionVerifier


def never_cancel(task_id: UUID) -> bool:
    del task_id
    return False


class RuntimeEngine:
    """Coordinate one validated and verified action per iteration."""

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        configuration: RuntimeConfiguration | None = None,
        cancellation_check: Callable[[UUID], bool] | None = None,
    ) -> None:
        self.event_store = event_store or InMemoryEventStore()
        self.configuration = configuration or RuntimeConfiguration()
        self.cancellation_check: Callable[[UUID], bool] = cancellation_check or never_cancel
        self.evaluator = ProgressEvaluator()
        self.policy = PolicyEngine()
        self.verifier = ActionVerifier()
        self._tasks: dict[UUID, Task] = {}
        self._approvals: dict[UUID, ApprovalRequest] = {}
        self._approved_actions: dict[UUID, Action] = {}
        self._cancelled: set[UUID] = set()

    def cancel(self, task_id: UUID) -> None:
        self._cancelled.add(task_id)

    def pending_approval(self, task_id: UUID) -> ApprovalRequest | None:
        request = self._approvals.get(task_id)
        return request if request is not None and request.status is ApprovalStatus.PENDING else None

    def approve(self, task_id: UUID) -> ApprovalRequest:
        request = self._require_pending_approval(task_id)
        now = datetime.now(UTC)
        approved = request.model_copy(
            update={"status": ApprovalStatus.APPROVED, "resolved_at": now}
        )
        self._approvals[task_id] = approved
        self._approved_actions[task_id] = approved.action
        self._append(task_id, RuntimeEventType.APPROVAL_GRANTED, {"approval_id": str(approved.id)})
        return approved

    def deny(self, task_id: UUID) -> ApprovalRequest:
        request = self._require_pending_approval(task_id)
        now = datetime.now(UTC)
        denied = request.model_copy(update={"status": ApprovalStatus.DENIED, "resolved_at": now})
        self._approvals[task_id] = denied
        self._append(task_id, RuntimeEventType.APPROVAL_DENIED, {"approval_id": str(denied.id)})
        task = self._tasks[task_id]
        blocked = self._with_status(task, TaskStatus.BLOCKED)
        self._tasks[task_id] = blocked
        self._append(
            task_id,
            RuntimeEventType.TASK_BLOCKED,
            {"reason": "approval denied"},
        )
        return denied

    async def run(
        self,
        task: Task,
        adapter: SimulationAdapter,
        decision_provider: DecisionProvider,
    ) -> RuntimeOutcome:
        task = self._prepare_task(task)
        iterations = 0
        consecutive_failures = 0
        repeated_action = 0
        repeated_state = 0
        last_action: str | None = None
        last_state: str | None = None
        reason: str | None = None

        try:
            task = self._with_status(task, TaskStatus.RUNNING)
            self._tasks[task.id] = task
            self._append(task.id, RuntimeEventType.TASK_STARTED, {})
            await adapter.initialize()
            observation = await adapter.observe()
            self._record_observation(task.id, observation)

            while task.status is TaskStatus.RUNNING:
                if self._is_cancelled(task.id):
                    task = self._terminal(task, TaskStatus.CANCELLED, "cancellation requested")
                    reason = "cancellation requested"
                    break
                if iterations >= self.configuration.max_iterations:
                    task = self._terminal(task, TaskStatus.BLOCKED, "maximum iterations reached")
                    reason = "maximum iterations reached"
                    break
                iterations += 1

                evaluation = self.evaluator.evaluate(task.specification, observation)
                self._append(
                    task.id,
                    RuntimeEventType.EVALUATION_RECORDED,
                    cast("dict[str, JsonValue]", evaluation.model_dump(mode="json")),
                )
                if evaluation.current_status is EvaluationStatus.COMPLETED:
                    task = self._terminal(task, TaskStatus.COMPLETED, evaluation.progress_summary)
                    reason = evaluation.progress_summary
                    break
                if evaluation.current_status is EvaluationStatus.BLOCKED:
                    reason = evaluation.blocked_reason or evaluation.progress_summary
                    task = self._terminal(task, TaskStatus.BLOCKED, reason)
                    break

                approved_action = self._approved_actions.pop(task.id, None)
                if approved_action is not None:
                    action = approved_action
                    decision = None
                else:
                    try:
                        decision = await decision_provider.decide(task, observation)
                    except ScriptedDecisionExhaustedError as error:
                        reason = str(error)
                        task = self._terminal(task, TaskStatus.BLOCKED, reason)
                        break
                    self._append(
                        task.id,
                        RuntimeEventType.DECISION_GENERATED,
                        cast("dict[str, JsonValue]", decision.model_dump(mode="json")),
                    )
                    if decision.type is DecisionType.COMPLETE:
                        reason = (
                            "decision provider claimed completion before evaluator confirmation"
                        )
                        self._append(
                            task.id,
                            RuntimeEventType.ACTION_REJECTED,
                            {"reason": reason},
                        )
                        consecutive_failures += 1
                        if self.configuration.block_on_false_completion:
                            task = self._terminal(task, TaskStatus.BLOCKED, reason)
                            break
                        if consecutive_failures >= self.configuration.max_consecutive_failures:
                            task = self._terminal(task, TaskStatus.BLOCKED, reason)
                            break
                        continue
                    if decision.type is DecisionType.BLOCKED:
                        reason = decision.reason
                        task = self._terminal(task, TaskStatus.BLOCKED, reason)
                        break
                    if decision.type is DecisionType.WAIT:
                        repeated_state += 1
                        if repeated_state >= self.configuration.repeated_state_limit:
                            reason = "repeated state detected"
                            task = self._terminal(task, TaskStatus.BLOCKED, reason)
                            break
                        continue
                    if decision.action is None:
                        reason = "decision requiring execution did not contain an action"
                        task = self._terminal(task, TaskStatus.FAILED, reason)
                        break
                    action = decision.action

                action_key = f"{action.model_dump_json()}::{observation.state!r}"
                repeated_action = repeated_action + 1 if action_key == last_action else 1
                last_action = action_key
                if repeated_action >= self.configuration.repeated_action_limit:
                    reason = "repeated action detected"
                    task = self._terminal(task, TaskStatus.BLOCKED, reason)
                    break

                adapter_validation = await adapter.validate(action)
                policy = self.policy.evaluate(
                    task.specification,
                    action,
                    observation,
                    task.total_spend,
                    adapter_validation,
                )
                self._append(
                    task.id,
                    RuntimeEventType.POLICY_VALIDATED,
                    cast("dict[str, JsonValue]", policy.model_dump(mode="json")),
                )
                if not policy.allowed:
                    reason = "; ".join(policy.reasons)
                    self._append(task.id, RuntimeEventType.ACTION_REJECTED, {"reason": reason})
                    consecutive_failures += 1
                    if consecutive_failures >= self.configuration.max_consecutive_failures:
                        task = self._terminal(task, TaskStatus.BLOCKED, reason)
                        break
                    continue
                was_approved = approved_action is not None
                approval_needed = policy.approval_required or (
                    decision is not None and decision.type is DecisionType.APPROVAL_REQUIRED
                )
                if approval_needed and not was_approved:
                    request = self._request_approval(task.id, action)
                    task = self._with_status(task, TaskStatus.WAITING_FOR_APPROVAL)
                    self._tasks[task.id] = task
                    reason = "approval required"
                    return self._outcome(task, iterations, reason, request)

                before = observation
                result = await adapter.execute(action)
                self._append(
                    task.id,
                    RuntimeEventType.ACTION_EXECUTED,
                    cast("dict[str, JsonValue]", result.model_dump(mode="json")),
                )
                observation = await adapter.observe()
                self._record_observation(task.id, observation)
                verification = self.verifier.verify(
                    before,
                    action,
                    result,
                    observation,
                    adapter_validation.estimated_cost,
                )
                self._append(
                    task.id,
                    RuntimeEventType.VERIFICATION_RECORDED,
                    cast("dict[str, JsonValue]", verification.model_dump(mode="json")),
                )
                if not verification.verified:
                    reason = "; ".join(verification.reasons)
                    task = self._terminal(task, TaskStatus.FAILED, reason)
                    break
                if not result.success:
                    consecutive_failures += 1
                    if consecutive_failures >= self.configuration.max_consecutive_failures:
                        reason = result.message
                        task = self._terminal(task, TaskStatus.BLOCKED, reason)
                        break
                else:
                    consecutive_failures = 0
                    task = task.model_copy(
                        update={
                            "total_spend": task.total_spend + Decimal(str(result.cost)),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    self._tasks[task.id] = task

                state_json = str(observation.state)
                repeated_state = repeated_state + 1 if state_json == last_state else 1
                last_state = state_json
                if repeated_state >= self.configuration.repeated_state_limit:
                    reason = "repeated state detected"
                    task = self._terminal(task, TaskStatus.BLOCKED, reason)
                    break
                if observation.state.get("failed") is True:
                    reason = "simulation entered terminal failure"
                    task = self._terminal(task, TaskStatus.FAILED, reason)
                    break
        except Exception as error:
            reason = f"runtime exception: {error}"
            if task.status is TaskStatus.RUNNING:
                task = self._terminal(task, TaskStatus.FAILED, reason)
        finally:
            try:
                await adapter.shutdown()
            except Exception as shutdown_error:
                if task.status is TaskStatus.RUNNING:
                    reason = f"adapter shutdown failed: {shutdown_error}"
                    task = self._terminal(task, TaskStatus.FAILED, reason)

        return self._outcome(task, iterations, reason)

    def _prepare_task(self, task: Task) -> Task:
        if task.status is TaskStatus.PENDING:
            if not self.event_store.list_events(task.id):
                self._append(task.id, RuntimeEventType.TASK_CREATED, {})
            self._tasks[task.id] = task
            return task
        if task.status is TaskStatus.WAITING_FOR_APPROVAL:
            known = self._tasks.get(task.id)
            if known is None or task.id not in self._approved_actions:
                msg = "task cannot resume without a granted approval"
                raise ValueError(msg)
            return known
        msg = f"task must be pending or waiting_for_approval, got {task.status.value}"
        raise ValueError(msg)

    def _with_status(self, task: Task, status: TaskStatus) -> Task:
        transition(task.status, status)
        now = datetime.now(UTC)
        return task.model_copy(update={"status": status, "updated_at": now})

    def _terminal(self, task: Task, status: TaskStatus, reason: str) -> Task:
        task = self._with_status(task, status)
        self._tasks[task.id] = task
        event_type = {
            TaskStatus.COMPLETED: RuntimeEventType.TASK_COMPLETED,
            TaskStatus.BLOCKED: RuntimeEventType.TASK_BLOCKED,
            TaskStatus.FAILED: RuntimeEventType.TASK_FAILED,
            TaskStatus.CANCELLED: RuntimeEventType.TASK_CANCELLED,
        }[status]
        self._append(task.id, event_type, {"reason": reason})
        return task

    def _request_approval(self, task_id: UUID, action: Action) -> ApprovalRequest:
        sequence = len(self.event_store.list_events(task_id)) + 1
        request = ApprovalRequest(
            id=uuid5(NAMESPACE_URL, f"sim-pilot:{task_id}:approval:{sequence}"),
            task_id=task_id,
            action=action,
            created_at=datetime.now(UTC),
        )
        self._approvals[task_id] = request
        self._append(
            task_id,
            RuntimeEventType.APPROVAL_REQUESTED,
            {"approval_id": str(request.id), "action_type": request.action.type},
        )
        return request

    def _require_pending_approval(self, task_id: UUID) -> ApprovalRequest:
        request = self._approvals.get(task_id)
        if request is None or request.status is not ApprovalStatus.PENDING:
            msg = "no pending approval exists for task"
            raise ValueError(msg)
        return request

    def _append(
        self,
        task_id: UUID,
        event_type: RuntimeEventType,
        payload: dict[str, JsonValue],
    ) -> None:
        sequence = len(self.event_store.list_events(task_id)) + 1
        self.event_store.append(
            RuntimeEvent(
                task_id=task_id,
                sequence=sequence,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                payload=payload,
            )
        )

    def _record_observation(self, task_id: UUID, observation: Observation) -> None:
        payload = cast("dict[str, JsonValue]", observation.model_dump(mode="json"))
        self._append(task_id, RuntimeEventType.OBSERVATION_RECORDED, payload)

    def _is_cancelled(self, task_id: UUID) -> bool:
        return task_id in self._cancelled or self.cancellation_check(task_id)

    def _outcome(
        self,
        task: Task,
        iterations: int,
        reason: str | None,
        approval: ApprovalRequest | None = None,
    ) -> RuntimeOutcome:
        return RuntimeOutcome(
            task_id=task.id,
            status=task.status,
            total_spend=float(task.total_spend),
            iterations=iterations,
            reason=reason,
            pending_approval=approval,
        )
