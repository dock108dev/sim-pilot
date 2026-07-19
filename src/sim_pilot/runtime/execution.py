"""Adapter-session and iteration orchestration behind the RuntimeEngine facade."""

import logging

from sim_pilot.adapters.base import SimulationAdapter
from sim_pilot.domain import Task, TaskStatus
from sim_pilot.domain.models import JsonValue
from sim_pilot.runtime.engine_support import (
    adapter_snapshot,
    force_failed,
    is_terminal,
    observation_draft,
    runtime_outcome,
    task_record,
    validate_restored_adapter,
    with_status,
)
from sim_pilot.runtime.errors import DurablePersistenceError
from sim_pilot.runtime.execution_services import RuntimeExecutionServices
from sim_pilot.runtime.interfaces import DecisionProvider
from sim_pilot.runtime.iteration import run_iterations
from sim_pilot.runtime.models import (
    RuntimeEventType,
    RuntimeOutcome,
)
from sim_pilot.runtime.persistence import (
    EventDraft,
)

logger = logging.getLogger(__name__)


async def run_runtime(
    services: RuntimeExecutionServices,
    task: Task,
    adapter: SimulationAdapter,
    decision_provider: DecisionProvider,
    *,
    iteration_budget: int | None = None,
) -> RuntimeOutcome:
    context = services.load_or_create(task)
    context = services.gate_recovery(context)
    if context.unresolved_attempt is not None:
        return runtime_outcome(
            context.task,
            context.runtime_state,
            "recovery intervention required",
            context,
        )
    if is_terminal(context.task.status):
        return runtime_outcome(context.task, context.runtime_state, context.reason, context)
    if (
        context.task.status is TaskStatus.WAITING_FOR_APPROVAL
        and context.pending_approval is not None
    ):
        return runtime_outcome(
            context.task,
            context.runtime_state,
            "approval required",
            context,
        )
    if context.task.status in {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_APPROVAL,
    }:
        validate_restored_adapter(adapter, context)

    current = task_record(context)
    runtime_state = context.runtime_state
    observation = context.observation
    initialization_attempted = False
    reason: str | None = None

    try:
        try:
            initialization_attempted = True
            await adapter.initialize()
            if context.task.status is TaskStatus.PENDING:
                running = with_status(context.task, TaskStatus.RUNNING)
                observation = await adapter.observe()
                commit = services.persistence.commit_iteration(
                    current,
                    task=running,
                    runtime_state=runtime_state,
                    event_drafts=(
                        EventDraft(RuntimeEventType.TASK_STARTED, {}),
                        observation_draft(observation),
                    ),
                    adapter_snapshot=adapter_snapshot(adapter, observation),
                )
                current = commit.task_record
            elif context.task.status is TaskStatus.WAITING_FOR_APPROVAL:
                running = with_status(context.task, TaskStatus.RUNNING)
                commit = services.persistence.commit_iteration(
                    current,
                    task=running,
                    runtime_state=runtime_state,
                    event_drafts=(EventDraft(RuntimeEventType.TASK_STARTED, {}),),
                )
                current = commit.task_record
                if getattr(adapter, "requires_fresh_observation_on_resume", False):
                    observation = await adapter.observe()
                    commit = services.persistence.commit_iteration(
                        current,
                        task=current.task,
                        runtime_state=runtime_state,
                        event_drafts=(observation_draft(observation),),
                        adapter_snapshot=adapter_snapshot(adapter, observation),
                    )
                    current = commit.task_record
            elif context.task.status is not TaskStatus.RUNNING:
                raise ValueError(f"task cannot run from {context.task.status.value}")
            elif getattr(adapter, "requires_fresh_observation_on_resume", False):
                observation = await adapter.observe()
                commit = services.persistence.commit_iteration(
                    current,
                    task=current.task,
                    runtime_state=runtime_state,
                    event_drafts=(observation_draft(observation),),
                    adapter_snapshot=adapter_snapshot(adapter, observation),
                )
                current = commit.task_record
            if observation is None:
                raise ValueError("running task has no reconstructed observation")
        except DurablePersistenceError:
            raise
        except Exception as error:
            reason = f"runtime exception: {error}"
            logger.exception(
                "unexpected runtime failure task_id=%s phase=adapter_initialization error_type=%s",
                current.task.id,
                type(error).__name__,
            )
            failed = force_failed(current.task)
            failure_payload: dict[str, JsonValue] = {
                "reason": reason,
                "error_type": type(error).__name__,
                "phase": "adapter_initialization",
            }
            commit = services.persistence.commit_iteration(
                current,
                task=failed,
                runtime_state=runtime_state,
                event_drafts=(
                    EventDraft(RuntimeEventType.TASK_STARTED, {}),
                    EventDraft(RuntimeEventType.TASK_FAILED, failure_payload),
                )
                if current.task.status is TaskStatus.PENDING
                else (EventDraft(RuntimeEventType.TASK_FAILED, failure_payload),),
            )
            current = commit.task_record
            return runtime_outcome(current.task, runtime_state, reason)

        loop_result = await run_iterations(
            services,
            current,
            runtime_state,
            observation,
            adapter,
            decision_provider,
            iteration_budget=iteration_budget,
        )
        current = loop_result.current
        runtime_state = loop_result.runtime_state
        observation = loop_result.observation
        reason = loop_result.reason
    finally:
        if initialization_attempted:
            try:
                await adapter.shutdown()
            except Exception as shutdown_error:
                logger.exception(
                    "adapter shutdown failed task_id=%s status=%s error_type=%s",
                    current.task.id,
                    current.task.status.value,
                    type(shutdown_error).__name__,
                )
                if current.task.status is TaskStatus.RUNNING:
                    reason = f"adapter shutdown failed: {shutdown_error}"
                    failed = with_status(current.task, TaskStatus.FAILED)
                    commit = services.persistence.commit_iteration(
                        current,
                        task=failed,
                        runtime_state=runtime_state,
                        event_drafts=(
                            EventDraft(
                                RuntimeEventType.TASK_FAILED,
                                {
                                    "reason": reason,
                                    "error_type": type(shutdown_error).__name__,
                                    "phase": "adapter_shutdown",
                                },
                            ),
                        ),
                        adapter_snapshot=(
                            adapter_snapshot(adapter, observation)
                            if observation is not None
                            else None
                        ),
                    )
                    current = commit.task_record

    context = services.reconstruct(current.task.id)
    return runtime_outcome(current.task, runtime_state, reason, context)
