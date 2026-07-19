"""Deterministic runtime with atomic durable iteration checkpoints."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sim_pilot.adapters.base import (
    AdapterSnapshot,
    SimulationAdapter,
)
from sim_pilot.domain import Observation, Task, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import (
    ApprovalRecord,
    RecordNotFoundError,
    TaskRecord,
    in_memory_unit_of_work_factory,
)
from sim_pilot.runtime.action_attempts import (
    ActionAttemptStatus,
    RecoveryResolution,
)
from sim_pilot.runtime.decision_context import DecisionContextProjector
from sim_pilot.runtime.engine_support import (
    action_state_fingerprint,
    adapter_snapshot,
    force_failed,
    is_terminal,
    observation_draft,
    runtime_outcome,
    task_record,
    validate_restored_adapter,
    with_status,
)
from sim_pilot.runtime.evaluator import ProgressEvaluator
from sim_pilot.runtime.execution import run_runtime
from sim_pilot.runtime.execution_services import RuntimeExecutionServices
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.models import (
    ApprovalRequest,
    ApprovalStatus,
    RuntimeConfiguration,
    RuntimeEventType,
    RuntimeOutcome,
    RuntimeSafeguardState,
)
from sim_pilot.runtime.persistence import (
    EventDraft,
    RepositoryEventView,
    RuntimePersistence,
    UnitOfWorkFactory,
)
from sim_pilot.runtime.policy import PolicyEngine
from sim_pilot.runtime.reconstruction import (
    ReconstructedRuntimeContext,
    RuntimeReconstructor,
)
from sim_pilot.runtime.recovery import (
    CrashPoint,
    ReconciliationDispatcher,
    ReconciliationReport,
)
from sim_pilot.runtime.verification import ActionVerifier

type AdapterFactory = Callable[[ReconstructedRuntimeContext], SimulationAdapter]
logger = logging.getLogger(__name__)


def never_cancel(task_id: UUID) -> bool:
    del task_id
    return False


class RuntimeEngine:
    """Coordinate one validated action per atomic, resumable iteration."""

    _action_fingerprint = staticmethod(action_state_fingerprint)
    _force_failed = staticmethod(force_failed)
    _is_terminal = staticmethod(is_terminal)
    _observation_draft = staticmethod(observation_draft)
    _outcome = staticmethod(runtime_outcome)
    _snapshot = staticmethod(adapter_snapshot)
    _task_record = staticmethod(task_record)
    _validate_restored_adapter = staticmethod(validate_restored_adapter)
    _with_status = staticmethod(with_status)

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory | None = None,
        configuration: RuntimeConfiguration | None = None,
        cancellation_check: Callable[[UUID], bool] | None = None,
        crash_hook: Callable[[CrashPoint], None] | None = None,
        reconciliation_dispatcher: ReconciliationDispatcher | None = None,
    ) -> None:
        if unit_of_work_factory is None:
            unit_of_work_factory = in_memory_unit_of_work_factory()
        self.persistence = RuntimePersistence(unit_of_work_factory)
        self.reconstructor = RuntimeReconstructor(unit_of_work_factory)
        self.event_store = RepositoryEventView(unit_of_work_factory)
        self.configuration = configuration or RuntimeConfiguration()
        self.decision_context_projector = DecisionContextProjector(
            max_recent_events=self.configuration.decision_context_event_limit,
            max_serialized_bytes=self.configuration.decision_context_max_bytes,
        )
        self.cancellation_check = cancellation_check or never_cancel
        self.crash_hook = crash_hook
        self.reconciliation_dispatcher = reconciliation_dispatcher or ReconciliationDispatcher()
        self.evaluator = ProgressEvaluator()
        self.policy = PolicyEngine()
        self.verifier = ActionVerifier()

    def create_task(self, task: Task) -> Task:
        """Atomically persist a pending task and its TaskCreated event."""
        if task.status is not TaskStatus.PENDING or task.sequence != 0:
            msg = "new task must be pending with sequence zero"
            raise ValueError(msg)
        return self.persistence.create_task(task).task

    def reconstruct(self, task_id: UUID) -> ReconstructedRuntimeContext:
        return self.reconstructor.load(task_id)

    def pending_approval(self, task_id: UUID) -> ApprovalRequest | None:
        try:
            context = self.reconstruct(task_id)
        except RecordNotFoundError:
            return None
        record = context.pending_approval
        return None if record is None else record.approval

    async def inspect_recovery(
        self,
        task_id: UUID,
        current_snapshot: AdapterSnapshot | None = None,
    ) -> ReconciliationReport | None:
        """Classify an unresolved attempt without mutating durable state."""
        context = self.reconstruct(task_id)
        attempt = context.unresolved_attempt
        if attempt is None:
            return None
        return await self.reconciliation_dispatcher.reconcile(
            attempt, context.adapter_snapshot(), current_snapshot
        )

    async def resolve_recovery(
        self,
        task_id: UUID,
        resolution: RecoveryResolution,
        *,
        current_snapshot: AdapterSnapshot | None = None,
    ) -> None:
        """Apply an explicit operator decision; never retry the interrupted action."""
        context = self.reconstruct(task_id)
        attempt = context.unresolved_attempt
        if attempt is None:
            raise ValueError("task has no unresolved action attempt")
        report = await self.reconciliation_dispatcher.reconcile(
            attempt, context.adapter_snapshot(), current_snapshot
        )
        payload: dict[str, JsonValue] = {
            "action_id": str(attempt.action_id),
            "classification": report.classification.value,
            "resolution": resolution.value,
            "reason": report.reason,
        }
        task_next = context.task
        snapshot: AdapterSnapshot | None = None
        drafts: list[EventDraft] = []
        runtime_state = context.runtime_state.model_copy(
            update={"approved_once_action": None, "approved_approval_id": None}
        )
        if resolution in {
            RecoveryResolution.ACCEPT_CURRENT,
            RecoveryResolution.MARK_EXECUTED,
        }:
            if current_snapshot is None or report.expected_result is None:
                raise ValueError("this resolution requires independently observed current state")
            previous = context.observation
            if previous is None:
                raise ValueError("recovery requires a prior observation")
            tick = current_snapshot.state.get("tick")
            if isinstance(tick, bool) or not isinstance(tick, int):
                raise ValueError("current adapter snapshot has an invalid tick")
            observation = Observation(
                sequence=previous.sequence + 1,
                timestamp=datetime.now(UTC),
                tick=tick,
                summary=f"Recovered state after action {attempt.action_id}.",
                state=cast("dict[str, object]", current_snapshot.state),
            )
            drafts.append(self._observation_draft(observation))
            result = report.expected_result
            if result.success:
                task_next = task_next.model_copy(
                    update={"total_spend": task_next.total_spend + Decimal(str(result.cost))}
                )
            snapshot = current_snapshot.model_copy(
                update={"observation_sequence": observation.sequence}
            )
        elif resolution is RecoveryResolution.ABANDON:
            task_next = self._with_status(task_next, TaskStatus.BLOCKED)
        elif resolution not in {
            RecoveryResolution.MARK_NOT_EXECUTED,
            RecoveryResolution.RESTORE_PRIOR_CHECKPOINT,
        }:
            raise ValueError(f"unsupported recovery resolution: {resolution.value}")
        drafts.append(EventDraft(RuntimeEventType.ACTION_RECONCILED, payload))
        if resolution is RecoveryResolution.ABANDON:
            drafts.append(
                EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": "recovery abandoned"})
            )
            snapshot = self.persistence.copy_checkpoint_for_terminal(context.checkpoint)
        self.persistence.commit_iteration(
            self._task_record(context),
            task=task_next,
            runtime_state=runtime_state,
            event_drafts=tuple(drafts),
            adapter_snapshot=snapshot,
        )

    def approve(self, task_id: UUID) -> ApprovalRequest:
        context = self.reconstruct(task_id)
        pending = context.pending_approval
        if pending is None:
            raise ValueError("no pending approval exists for task")
        now = datetime.now(UTC)
        approved = pending.approval.model_copy(
            update={"status": ApprovalStatus.APPROVED, "resolved_at": now}
        )
        runtime_state = context.runtime_state.model_copy(
            update={
                "approved_once_action": approved.action,
                "approved_approval_id": approved.id,
            }
        )
        current = self._task_record(context)
        self.persistence.commit_iteration(
            current,
            task=context.task,
            runtime_state=runtime_state,
            event_drafts=(
                EventDraft(
                    RuntimeEventType.APPROVAL_GRANTED,
                    {"approval_id": str(approved.id)},
                ),
            ),
            approval_update=ApprovalRecord(approval=approved, reason="approval granted"),
        )
        return approved

    def deny(self, task_id: UUID) -> ApprovalRequest:
        context = self.reconstruct(task_id)
        pending = context.pending_approval
        if pending is None:
            raise ValueError("no pending approval exists for task")
        now = datetime.now(UTC)
        denied = pending.approval.model_copy(
            update={"status": ApprovalStatus.DENIED, "resolved_at": now}
        )
        blocked = self._with_status(context.task, TaskStatus.BLOCKED)
        self.persistence.commit_iteration(
            self._task_record(context),
            task=blocked,
            runtime_state=context.runtime_state,
            event_drafts=(
                EventDraft(RuntimeEventType.APPROVAL_DENIED, {"approval_id": str(denied.id)}),
                EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": "approval denied"}),
            ),
            approval_update=ApprovalRecord(approval=denied, reason="approval denied"),
            adapter_snapshot=self.persistence.copy_checkpoint_for_terminal(context.checkpoint),
        )
        return denied

    def cancel(self, task_id: UUID) -> None:
        context = self.reconstruct(task_id)
        if context.task.status in {
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            return
        cancelled = self._with_status(context.task, TaskStatus.CANCELLED)
        self.persistence.commit_iteration(
            self._task_record(context),
            task=cancelled,
            runtime_state=context.runtime_state,
            cancel_requested=True,
            event_drafts=(
                EventDraft(RuntimeEventType.TASK_CANCELLED, {"reason": "cancellation requested"}),
            ),
            adapter_snapshot=self.persistence.copy_checkpoint_for_terminal(context.checkpoint),
        )

    async def resume(
        self,
        task_id: UUID,
        adapter_factory: AdapterFactory,
        decision_provider: DecisionProvider,
        *,
        iteration_budget: int | None = None,
    ) -> RuntimeOutcome:
        context = self.reconstruct(task_id)
        context = self._gate_recovery(context)
        if context.unresolved_attempt is not None:
            return self._outcome(
                context.task,
                context.runtime_state,
                "recovery intervention required",
                context,
            )
        if self._is_terminal(context.task.status) or (
            context.task.status is TaskStatus.WAITING_FOR_APPROVAL
            and context.pending_approval is not None
        ):
            return self._outcome(context.task, context.runtime_state, context.reason, context)
        adapter = adapter_factory(context)
        return await self.run(
            context.task,
            adapter,
            decision_provider,
            iteration_budget=iteration_budget,
        )

    async def run(
        self,
        task: Task,
        adapter: SimulationAdapter,
        decision_provider: DecisionProvider,
        *,
        iteration_budget: int | None = None,
    ) -> RuntimeOutcome:
        """Execute a task through the dedicated runtime execution coordinator."""
        services = RuntimeExecutionServices(
            persistence=self.persistence,
            configuration=self.configuration,
            decision_context_projector=self.decision_context_projector,
            cancellation_check=self.cancellation_check,
            evaluator=self.evaluator,
            policy=self.policy,
            verifier=self.verifier,
            event_store=self.event_store,
            reconstruct=self.reconstruct,
            load_or_create=self._load_or_create,
            gate_recovery=self._gate_recovery,
            crash=self._crash,
            commit_terminal=self._commit_terminal,
            commit_with_drafts=self._commit_with_drafts,
            observation_history=self._observation_history,
        )
        return await run_runtime(
            services,
            task,
            adapter,
            decision_provider,
            iteration_budget=iteration_budget,
        )

    def _load_or_create(self, task: Task) -> ReconstructedRuntimeContext:
        try:
            return self.reconstruct(task.id)
        except RecordNotFoundError:
            self.create_task(task)
            return self.reconstruct(task.id)

    def _gate_recovery(self, context: ReconstructedRuntimeContext) -> ReconstructedRuntimeContext:
        attempt = context.unresolved_attempt
        if attempt is None:
            return context
        current = self._task_record(context)
        if attempt.status is ActionAttemptStatus.PREPARED:
            self.persistence.commit_iteration(
                current,
                task=context.task,
                runtime_state=context.runtime_state,
                event_drafts=(
                    EventDraft(
                        RuntimeEventType.ACTION_RECONCILED,
                        {
                            "action_id": str(attempt.action_id),
                            "classification": "definitely_not_executed",
                            "resolution": "mark_not_executed",
                            "reason": "execution boundary was never entered",
                        },
                    ),
                ),
            )
            return self.reconstruct(context.task.id)
        if attempt.status is not ActionAttemptStatus.RECONCILIATION_REQUIRED:
            self.persistence.commit_iteration(
                current,
                task=context.task,
                runtime_state=context.runtime_state,
                event_drafts=(
                    EventDraft(
                        RuntimeEventType.ACTION_RECONCILIATION_REQUIRED,
                        {
                            "action_id": str(attempt.action_id),
                            "reason": "execution began without a committed checkpoint",
                        },
                    ),
                ),
            )
            return self.reconstruct(context.task.id)
        return context

    def _crash(self, point: CrashPoint) -> None:
        if self.crash_hook is not None:
            self.crash_hook(point)

    def _commit_terminal(
        self,
        current: TaskRecord,
        runtime_state: RuntimeSafeguardState,
        adapter: SimulationAdapter,
        observation: Observation,
        status: TaskStatus,
        reason: str,
        prefix: tuple[EventDraft, ...] = (),
    ) -> tuple[TaskRecord, str]:
        event_type = {
            TaskStatus.BLOCKED: RuntimeEventType.TASK_BLOCKED,
            TaskStatus.FAILED: RuntimeEventType.TASK_FAILED,
            TaskStatus.COMPLETED: RuntimeEventType.TASK_COMPLETED,
        }[status]
        task = self._with_status(current.task, status)
        record = self._commit_with_drafts(
            current,
            task,
            runtime_state,
            (*prefix, EventDraft(event_type, {"reason": reason})),
            self._snapshot(adapter, observation),
        )
        return record, reason

    def _commit_with_drafts(
        self,
        current: TaskRecord,
        task: Task,
        runtime_state: RuntimeSafeguardState,
        drafts: tuple[EventDraft, ...],
        snapshot: AdapterSnapshot | None,
    ) -> TaskRecord:
        return self.persistence.commit_iteration(
            current,
            task=task,
            runtime_state=runtime_state,
            event_drafts=drafts,
            adapter_snapshot=snapshot,
        ).task_record

    def _observation_history(self, task_id: UUID) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        for event in self.event_store.list_events(task_id):
            if event.event_type is not RuntimeEventType.OBSERVATION_RECORDED:
                continue
            try:
                observations.append(Observation.model_validate_json(json.dumps(event.payload)))
            except ValueError:
                continue
        return tuple(observations)
