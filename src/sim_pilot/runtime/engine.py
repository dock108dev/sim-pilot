"""Deterministic runtime with atomic durable iteration checkpoints."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sim_pilot.adapters.base import (
    AdapterSnapshot,
    CheckpointableSimulationAdapter,
    SimulationAdapter,
)
from sim_pilot.domain import Action, DecisionType, Observation, Task, TaskStatus
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
    action_fingerprint,
    observation_fingerprint,
)
from sim_pilot.runtime.decision_context import DecisionContextProjector
from sim_pilot.runtime.decision_errors import DecisionProviderError
from sim_pilot.runtime.decisions import ScriptedDecisionExhaustedError
from sim_pilot.runtime.errors import DurablePersistenceError
from sim_pilot.runtime.evaluator import ProgressEvaluator
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.lifecycle import transition
from sim_pilot.runtime.models import (
    ApprovalRequest,
    ApprovalStatus,
    EvaluationStatus,
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
    ReconciliationReport,
    reconcile_action,
)
from sim_pilot.runtime.verification import ActionVerifier

type AdapterFactory = Callable[[ReconstructedRuntimeContext], SimulationAdapter]


def never_cancel(task_id: UUID) -> bool:
    del task_id
    return False


class RuntimeEngine:
    """Coordinate one validated action per atomic, resumable iteration."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory | None = None,
        configuration: RuntimeConfiguration | None = None,
        cancellation_check: Callable[[UUID], bool] | None = None,
        crash_hook: Callable[[CrashPoint], None] | None = None,
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
        return await reconcile_action(attempt, context.adapter_snapshot(), current_snapshot)

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
        report = await reconcile_action(attempt, context.adapter_snapshot(), current_snapshot)
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
        context = self._load_or_create(task)
        context = self._gate_recovery(context)
        if context.unresolved_attempt is not None:
            return self._outcome(
                context.task,
                context.runtime_state,
                "recovery intervention required",
                context,
            )
        if self._is_terminal(context.task.status):
            return self._outcome(context.task, context.runtime_state, context.reason, context)
        if (
            context.task.status is TaskStatus.WAITING_FOR_APPROVAL
            and context.pending_approval is not None
        ):
            return self._outcome(
                context.task,
                context.runtime_state,
                "approval required",
                context,
            )
        if context.task.status in {
            TaskStatus.RUNNING,
            TaskStatus.WAITING_FOR_APPROVAL,
        }:
            self._validate_restored_adapter(adapter, context)

        current = self._task_record(context)
        runtime_state = context.runtime_state
        observation = context.observation
        initialization_attempted = False
        committed_this_run = 0
        reason: str | None = None
        active_action_id: UUID | None = None

        try:
            try:
                initialization_attempted = True
                await adapter.initialize()
                if context.task.status is TaskStatus.PENDING:
                    running = self._with_status(context.task, TaskStatus.RUNNING)
                    observation = await adapter.observe()
                    commit = self.persistence.commit_iteration(
                        current,
                        task=running,
                        runtime_state=runtime_state,
                        event_drafts=(
                            EventDraft(RuntimeEventType.TASK_STARTED, {}),
                            self._observation_draft(observation),
                        ),
                        adapter_snapshot=self._snapshot(adapter, observation),
                    )
                    current = commit.task_record
                elif context.task.status is TaskStatus.WAITING_FOR_APPROVAL:
                    running = self._with_status(context.task, TaskStatus.RUNNING)
                    commit = self.persistence.commit_iteration(
                        current,
                        task=running,
                        runtime_state=runtime_state,
                        event_drafts=(EventDraft(RuntimeEventType.TASK_STARTED, {}),),
                    )
                    current = commit.task_record
                    if getattr(adapter, "requires_fresh_observation_on_resume", False):
                        observation = await adapter.observe()
                        commit = self.persistence.commit_iteration(
                            current,
                            task=current.task,
                            runtime_state=runtime_state,
                            event_drafts=(self._observation_draft(observation),),
                            adapter_snapshot=self._snapshot(adapter, observation),
                        )
                        current = commit.task_record
                elif context.task.status is not TaskStatus.RUNNING:
                    raise ValueError(f"task cannot run from {context.task.status.value}")
                elif getattr(adapter, "requires_fresh_observation_on_resume", False):
                    observation = await adapter.observe()
                    commit = self.persistence.commit_iteration(
                        current,
                        task=current.task,
                        runtime_state=runtime_state,
                        event_drafts=(self._observation_draft(observation),),
                        adapter_snapshot=self._snapshot(adapter, observation),
                    )
                    current = commit.task_record
                if observation is None:
                    raise ValueError("running task has no reconstructed observation")
            except DurablePersistenceError:
                raise
            except Exception as error:
                reason = f"runtime exception: {error}"
                failed = self._force_failed(current.task)
                commit = self.persistence.commit_iteration(
                    current,
                    task=failed,
                    runtime_state=runtime_state,
                    event_drafts=(
                        EventDraft(RuntimeEventType.TASK_STARTED, {}),
                        EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}),
                    )
                    if current.task.status is TaskStatus.PENDING
                    else (EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}),),
                )
                current = commit.task_record
                return self._outcome(current.task, runtime_state, reason)

            while current.task.status is TaskStatus.RUNNING:
                if iteration_budget is not None and committed_this_run >= iteration_budget:
                    reason = "execution slice complete"
                    break
                if current.cancel_requested or self.cancellation_check(current.task.id):
                    cancelled = self._with_status(current.task, TaskStatus.CANCELLED)
                    commit = self.persistence.commit_iteration(
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
                        adapter_snapshot=self._snapshot(adapter, observation),
                    )
                    current = commit.task_record
                    reason = "cancellation requested"
                    break
                if runtime_state.iterations >= self.configuration.max_iterations:
                    current, reason = self._commit_terminal(
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
                evaluation = self.evaluator.evaluate(
                    current.task.specification,
                    observation,
                    observation_history=self._observation_history(current.task.id),
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
                    current = self._commit_with_drafts(
                        current,
                        self._with_status(current.task, TaskStatus.COMPLETED),
                        runtime_state,
                        tuple(drafts),
                        self._snapshot(adapter, observation),
                    )
                    reason = evaluation.progress_summary
                    break
                if evaluation.current_status is EvaluationStatus.BLOCKED:
                    reason = evaluation.blocked_reason or evaluation.progress_summary
                    drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                    current = self._commit_with_drafts(
                        current,
                        self._with_status(current.task, TaskStatus.BLOCKED),
                        runtime_state,
                        tuple(drafts),
                        self._snapshot(adapter, observation),
                    )
                    break

                approved_action = runtime_state.approved_once_action
                decision = None
                if approved_action is None:
                    try:
                        available_actions = await adapter.available_actions()
                        decision_context = self.decision_context_projector.project(
                            task=current.task,
                            observation=observation,
                            available_actions=available_actions,
                            events=self.event_store.list_events(current.task.id),
                            runtime_state=runtime_state,
                            progress=evaluation,
                        )
                        provider_result = await decision_provider.decide(decision_context)
                        decision = provider_result.decision
                    except ScriptedDecisionExhaustedError as error:
                        reason = str(error)
                        drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                        current = self._commit_with_drafts(
                            current,
                            self._with_status(current.task, TaskStatus.BLOCKED),
                            runtime_state,
                            tuple(drafts),
                            self._snapshot(adapter, observation),
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
                        current = self._commit_with_drafts(
                            current,
                            self._with_status(current.task, TaskStatus.FAILED),
                            runtime_state,
                            tuple(drafts),
                            self._snapshot(adapter, observation),
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
                        reason = (
                            "decision provider claimed completion before evaluator confirmation"
                        )
                        drafts.append(
                            EventDraft(RuntimeEventType.ACTION_REJECTED, {"reason": reason})
                        )
                        runtime_state = runtime_state.model_copy(
                            update={
                                "consecutive_failures": runtime_state.consecutive_failures + 1,
                                "rejected_action_count": runtime_state.rejected_action_count + 1,
                            }
                        )
                        if (
                            self.configuration.block_on_false_completion
                            or runtime_state.consecutive_failures
                            >= self.configuration.max_consecutive_failures
                        ):
                            drafts.append(
                                EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason})
                            )
                            task_next = self._with_status(current.task, TaskStatus.BLOCKED)
                            snapshot = self._snapshot(adapter, observation)
                        else:
                            task_next = current.task
                            snapshot = None
                        current = self._commit_with_drafts(
                            current, task_next, runtime_state, tuple(drafts), snapshot
                        )
                        committed_this_run += 1
                        if task_next.status is TaskStatus.BLOCKED:
                            break
                        continue
                    if decision.type is DecisionType.BLOCKED:
                        reason = decision.reason
                        drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                        current = self._commit_with_drafts(
                            current,
                            self._with_status(current.task, TaskStatus.BLOCKED),
                            runtime_state,
                            tuple(drafts),
                            self._snapshot(adapter, observation),
                        )
                        break
                    if decision.type is DecisionType.WAIT:
                        external_refresh = bool(
                            getattr(adapter, "requires_fresh_observation_on_resume", False)
                        )
                        if external_refresh:
                            observation = await adapter.observe()
                            drafts.append(self._observation_draft(observation))
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
                        if repeated >= self.configuration.repeated_state_limit:
                            reason = "repeated state detected"
                            drafts.append(
                                EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason})
                            )
                            task_next = self._with_status(current.task, TaskStatus.BLOCKED)
                            snapshot = self._snapshot(adapter, observation)
                        else:
                            task_next = current.task
                            snapshot = (
                                self._snapshot(adapter, observation) if external_refresh else None
                            )
                        current = self._commit_with_drafts(
                            current, task_next, runtime_state, tuple(drafts), snapshot
                        )
                        committed_this_run += 1
                        if task_next.status is TaskStatus.BLOCKED:
                            break
                        continue
                    if decision.action is None:
                        reason = "decision requiring execution did not contain an action"
                        drafts.append(EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}))
                        current = self._commit_with_drafts(
                            current,
                            self._with_status(current.task, TaskStatus.FAILED),
                            runtime_state,
                            tuple(drafts),
                            self._snapshot(adapter, observation),
                        )
                        break
                    action = decision.action
                else:
                    action = approved_action

                fingerprint = self._action_fingerprint(action, observation)
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
                    and repeated_action >= self.configuration.repeated_action_limit
                ):
                    reason = "repeated action detected"
                    drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                    current = self._commit_with_drafts(
                        current,
                        self._with_status(current.task, TaskStatus.BLOCKED),
                        runtime_state,
                        tuple(drafts),
                        self._snapshot(adapter, observation),
                    )
                    break

                adapter_validation = await adapter.validate(action)
                policy = self.policy.evaluate(
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
                        drafts.append(self._observation_draft(observation))
                    if (
                        runtime_state.consecutive_failures
                        >= self.configuration.max_consecutive_failures
                    ):
                        drafts.append(EventDraft(RuntimeEventType.TASK_BLOCKED, {"reason": reason}))
                        task_next = self._with_status(current.task, TaskStatus.BLOCKED)
                        snapshot = self._snapshot(adapter, observation)
                    else:
                        task_next = current.task
                        snapshot = self._snapshot(adapter, observation) if stale else None
                    current = self._commit_with_drafts(
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
                    waiting = self._with_status(current.task, TaskStatus.WAITING_FOR_APPROVAL)
                    commit = self.persistence.commit_iteration(
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

                before = observation
                latest_checkpoint = self.reconstruct(current.task.id).checkpoint
                attempt_sequence = current.task.sequence + len(drafts) + 1
                action_id = uuid5(
                    NAMESPACE_URL,
                    f"sim-pilot:{current.task.id}:action-attempt:{attempt_sequence}",
                )
                active_action_id = action_id
                drafts.append(
                    EventDraft(
                        RuntimeEventType.ACTION_PREPARED,
                        {
                            "action_id": str(action_id),
                            "action_fingerprint": action_fingerprint(action),
                            "action": cast("dict[str, JsonValue]", action.model_dump(mode="json")),
                            "prior_checkpoint_id": (
                                None
                                if latest_checkpoint is None
                                else str(latest_checkpoint.metadata.id)
                            ),
                            "prior_observation_fingerprint": observation_fingerprint(before),
                            "expected_effect": action.expected_effect,
                            "estimated_cost": float(adapter_validation.estimated_cost),
                        },
                    )
                )
                current = self._commit_with_drafts(
                    current, current.task, runtime_state, tuple(drafts), None
                )
                drafts = []
                self._crash(CrashPoint.AFTER_PREPARED)
                current = self._commit_with_drafts(
                    current,
                    current.task,
                    runtime_state,
                    (
                        EventDraft(
                            RuntimeEventType.ACTION_EXECUTION_STARTED,
                            {"action_id": str(action_id)},
                        ),
                    ),
                    None,
                )
                self._crash(CrashPoint.BEFORE_EXECUTION)
                result = await adapter.execute(action)
                self._crash(CrashPoint.AFTER_EXECUTION)
                drafts.append(
                    EventDraft(
                        RuntimeEventType.ACTION_EXECUTED,
                        cast("dict[str, JsonValue]", result.model_dump(mode="json")),
                    )
                )
                observation = await adapter.observe()
                self._crash(CrashPoint.AFTER_OBSERVATION)
                drafts.append(self._observation_draft(observation))
                verification = self.verifier.verify(
                    before,
                    action,
                    result,
                    observation,
                    adapter_validation.estimated_cost,
                )
                drafts.append(
                    EventDraft(
                        RuntimeEventType.VERIFICATION_RECORDED,
                        cast("dict[str, JsonValue]", verification.model_dump(mode="json")),
                    )
                )
                self._crash(CrashPoint.AFTER_VERIFICATION)
                runtime_state = runtime_state.model_copy(
                    update={"approved_once_action": None, "approved_approval_id": None}
                )
                task_next = current.task
                terminal_status: TaskStatus | None = None
                if not verification.verified:
                    reason = "; ".join(verification.reasons)
                    terminal_status = TaskStatus.FAILED
                elif not result.success:
                    failures = runtime_state.consecutive_failures + 1
                    runtime_state = runtime_state.model_copy(
                        update={"consecutive_failures": failures}
                    )
                    if failures >= self.configuration.max_consecutive_failures:
                        reason = result.message
                        terminal_status = TaskStatus.BLOCKED
                else:
                    runtime_state = runtime_state.model_copy(update={"consecutive_failures": 0})
                    task_next = current.task.model_copy(
                        update={
                            "total_spend": current.task.total_spend + Decimal(str(result.cost)),
                        }
                    )

                state_fingerprint = json.dumps(
                    observation.state, sort_keys=True, separators=(",", ":")
                )
                repeated_state = (
                    runtime_state.repeated_state_count + 1
                    if state_fingerprint == runtime_state.last_state_fingerprint
                    else 1
                )
                runtime_state = runtime_state.model_copy(
                    update={
                        "last_state_fingerprint": state_fingerprint,
                        "repeated_state_count": repeated_state,
                    }
                )
                if (
                    terminal_status is None
                    and repeated_state >= self.configuration.repeated_state_limit
                ):
                    reason = "repeated state detected"
                    terminal_status = TaskStatus.BLOCKED
                if terminal_status is None and observation.state.get("failed") is True:
                    reason = "simulation entered terminal failure"
                    terminal_status = TaskStatus.FAILED
                terminal_draft: EventDraft | None = None
                if terminal_status is not None:
                    task_next = self._with_status(task_next, terminal_status)
                    event_type = {
                        TaskStatus.BLOCKED: RuntimeEventType.TASK_BLOCKED,
                        TaskStatus.FAILED: RuntimeEventType.TASK_FAILED,
                    }[terminal_status]
                    terminal_draft = EventDraft(event_type, {"reason": cast("str", reason)})
                drafts.append(
                    EventDraft(
                        RuntimeEventType.ACTION_EXECUTION_CONFIRMED,
                        {
                            "action_id": str(action_id),
                            "success": result.success,
                            "verified": verification.verified,
                        },
                    )
                )
                drafts.append(
                    EventDraft(
                        RuntimeEventType.ACTION_CHECKPOINT_COMMITTED,
                        {"action_id": str(action_id)},
                    )
                )
                if terminal_draft is not None:
                    drafts.append(terminal_draft)
                snapshot = (
                    self._snapshot(adapter, observation)
                    if result.state_changed or terminal_status is not None
                    else None
                )
                current = self._commit_with_drafts(
                    current, task_next, runtime_state, tuple(drafts), snapshot
                )
                active_action_id = None
                self._crash(CrashPoint.AFTER_COMMIT)
                committed_this_run += 1
                if terminal_status is not None:
                    break
        except DurablePersistenceError:
            raise
        except Exception as error:
            reason = f"runtime exception: {error}"
            if current.task.status is TaskStatus.RUNNING:
                failed = self._with_status(current.task, TaskStatus.FAILED)
                snapshot = self._snapshot(adapter, observation) if observation is not None else None
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
                commit = self.persistence.commit_iteration(
                    current,
                    task=failed,
                    runtime_state=runtime_state,
                    event_drafts=(
                        *failure_drafts,
                        EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}),
                    ),
                    adapter_snapshot=snapshot,
                )
                current = commit.task_record
        finally:
            if initialization_attempted:
                try:
                    await adapter.shutdown()
                except Exception as shutdown_error:
                    if current.task.status is TaskStatus.RUNNING:
                        reason = f"adapter shutdown failed: {shutdown_error}"
                        failed = self._with_status(current.task, TaskStatus.FAILED)
                        commit = self.persistence.commit_iteration(
                            current,
                            task=failed,
                            runtime_state=runtime_state,
                            event_drafts=(
                                EventDraft(RuntimeEventType.TASK_FAILED, {"reason": reason}),
                            ),
                            adapter_snapshot=(
                                self._snapshot(adapter, observation)
                                if observation is not None
                                else None
                            ),
                        )
                        current = commit.task_record

        context = self.reconstruct(current.task.id)
        return self._outcome(current.task, runtime_state, reason, context)

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

    @staticmethod
    def _task_record(context: ReconstructedRuntimeContext) -> TaskRecord:
        return TaskRecord(
            task=context.task,
            cancel_requested=context.cancel_requested,
            runtime_state=context.runtime_state,
        )

    @staticmethod
    def _with_status(task: Task, status: TaskStatus) -> Task:
        transition(task.status, status)
        return task.model_copy(update={"status": status})

    @staticmethod
    def _force_failed(task: Task) -> Task:
        if task.status is TaskStatus.PENDING:
            transition(task.status, TaskStatus.RUNNING)
        return task.model_copy(update={"status": TaskStatus.FAILED})

    @staticmethod
    def _observation_draft(observation: Observation) -> EventDraft:
        return EventDraft(
            RuntimeEventType.OBSERVATION_RECORDED,
            cast("dict[str, JsonValue]", observation.model_dump(mode="json")),
        )

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

    @staticmethod
    def _snapshot(adapter: SimulationAdapter, observation: Observation) -> AdapterSnapshot:
        if isinstance(adapter, CheckpointableSimulationAdapter):
            return adapter.snapshot()
        schema_version = observation.state.get("schema_version", 1)
        if not isinstance(schema_version, int):
            schema_version = 1
        return AdapterSnapshot(
            adapter_type=f"{type(adapter).__module__}.{type(adapter).__qualname__}",
            simulation_schema_version=schema_version,
            observation_sequence=observation.sequence,
            seed="0",
            state=cast("dict[str, JsonValue]", observation.state),
        )

    @staticmethod
    def _action_fingerprint(action: Action, observation: Observation) -> str:
        return json.dumps(
            {
                "action": action.model_dump(mode="json"),
                "state": observation.state,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _validate_restored_adapter(
        adapter: SimulationAdapter, context: ReconstructedRuntimeContext
    ) -> None:
        if not isinstance(adapter, CheckpointableSimulationAdapter):
            return
        expected = context.adapter_snapshot()
        actual = adapter.snapshot()
        if actual != expected:
            from sim_pilot.runtime.errors import ReconstructionConsistencyError

            raise ReconstructionConsistencyError(
                "restored adapter does not match the latest durable checkpoint"
            )

    @staticmethod
    def _is_terminal(status: TaskStatus) -> bool:
        return status in {
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

    @staticmethod
    def _outcome(
        task: Task,
        runtime_state: RuntimeSafeguardState,
        reason: str | None,
        context: ReconstructedRuntimeContext | None = None,
    ) -> RuntimeOutcome:
        pending = None
        if context is not None and context.pending_approval is not None:
            pending = context.pending_approval.approval
        return RuntimeOutcome(
            task_id=task.id,
            status=task.status,
            total_spend=float(task.total_spend),
            iterations=runtime_state.iterations,
            reason=reason,
            pending_approval=pending,
        )
