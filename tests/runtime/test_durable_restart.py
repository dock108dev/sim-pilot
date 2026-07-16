"""Task 4B process-level SQLite reconstruction and resume scenarios."""

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import (
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    Task,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.persistence.sqlite import (
    SQLiteUnitOfWork,
    create_sqlite_engine,
    upgrade_database,
)
from sim_pilot.runtime import (
    DurablePersistenceError,
    ReconstructionConsistencyError,
    RuntimeEngine,
    ScriptedDecisionProvider,
)
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType
from sim_pilot.runtime.reconstruction import ReconstructedRuntimeContext
from tests.runtime.helpers import make_action, make_task


def execute_advance() -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason="Advance one deterministic tick.",
        action=make_action("advance_time", ticks=1),
    )


def execute_build() -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason="Build housing.",
        action=make_action("build_housing", units=100),
    )


def open_runtime(database_url: str) -> tuple[Engine, RuntimeEngine]:
    engine = create_sqlite_engine(database_url)
    runtime = RuntimeEngine(unit_of_work_factory=lambda: SQLiteUnitOfWork(engine))
    return engine, runtime


def restore_reference(context: ReconstructedRuntimeContext) -> ReferenceSimulationAdapter:
    if context.checkpoint is None:
        return ReferenceSimulationAdapter()
    return ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot())


def semantic_events(events: tuple[RuntimeEvent, ...]) -> tuple[tuple[str, object], ...]:
    normalized: list[tuple[str, object]] = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type is RuntimeEventType.OBSERVATION_RECORDED:
            payload.pop("timestamp", None)
        normalized.append((event.event_type.value, payload))
    return tuple(normalized)


def test_scenario_a_and_i_running_resume_matches_uninterrupted_execution(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        interrupted_url = f"sqlite:///{tmp_path / 'interrupted.db'}"
        uninterrupted_url = f"sqlite:///{tmp_path / 'uninterrupted.db'}"
        upgrade_database(interrupted_url)
        upgrade_database(uninterrupted_url)
        decisions = [execute_advance() for _ in range(10)]

        engine1, runtime1 = open_runtime(interrupted_url)
        task = make_task(target=520_000)
        partial = await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider(decisions),
            iteration_budget=1,
        )
        assert partial.status is TaskStatus.RUNNING
        partial_context = runtime1.reconstruct(task.id)
        partial_tick = partial_context.checkpoint.metadata.simulation_tick  # type: ignore[union-attr]
        engine1.dispose()

        engine2, runtime2 = open_runtime(interrupted_url)
        resumed = await runtime2.resume(
            task.id,
            restore_reference,
            ScriptedDecisionProvider(decisions[1:]),
        )
        resumed_context = runtime2.reconstruct(task.id)
        assert resumed.status is TaskStatus.COMPLETED
        assert resumed_context.checkpoint is not None
        assert resumed_context.checkpoint.metadata.simulation_tick > partial_tick
        engine2.dispose()

        engine3, uninterrupted_runtime = open_runtime(uninterrupted_url)
        uninterrupted = await uninterrupted_runtime.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider(decisions),
        )
        uninterrupted_context = uninterrupted_runtime.reconstruct(task.id)
        assert uninterrupted.status is TaskStatus.COMPLETED
        assert resumed_context.checkpoint is not None
        assert uninterrupted_context.checkpoint is not None
        assert resumed_context.checkpoint.state == uninterrupted_context.checkpoint.state
        assert resumed_context.task.total_spend == uninterrupted_context.task.total_spend
        assert semantic_events(resumed_context.events) == semantic_events(
            uninterrupted_context.events
        )
        engine3.dispose()

    asyncio.run(scenario())


def test_scenario_b_pending_task_starts_after_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'pending.db'}"
        upgrade_database(url)
        engine1, runtime1 = open_runtime(url)
        task = make_task(target=505_000)
        runtime1.create_task(task)
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        outcome = await runtime2.resume(
            task.id,
            restore_reference,
            ScriptedDecisionProvider([execute_advance() for _ in range(3)]),
        )
        assert outcome.status is TaskStatus.COMPLETED
        engine2.dispose()

    asyncio.run(scenario())


def approval_task() -> Task:
    specification = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach cash target.",
            parameters={"resource": "cash", "target": 1_000_000},
        ),
        authority=AuthorityPolicy(maximum_single_spend=Decimal(50_000)),
    )
    return make_task(specification=specification)


def test_scenario_c_waiting_approval_survives_two_restarts_and_executes_once(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'approval.db'}"
        upgrade_database(url)
        task = approval_task()
        task_id = task.id
        engine1, runtime1 = open_runtime(url)
        waiting = await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider([execute_build()]),
        )
        assert waiting.status is TaskStatus.WAITING_FOR_APPROVAL
        engine1.dispose()

        factory_calls = 0

        def must_not_restore(context: ReconstructedRuntimeContext) -> ReferenceSimulationAdapter:
            nonlocal factory_calls
            factory_calls += 1
            return restore_reference(context)

        engine2, runtime2 = open_runtime(url)
        still_waiting = await runtime2.resume(
            task_id,
            must_not_restore,
            ScriptedDecisionProvider([]),
        )
        assert still_waiting.status is TaskStatus.WAITING_FOR_APPROVAL
        assert factory_calls == 0
        runtime2.approve(task_id)
        engine2.dispose()

        engine3, runtime3 = open_runtime(url)
        finished = await runtime3.resume(
            task_id,
            restore_reference,
            ScriptedDecisionProvider(
                [Decision(type=DecisionType.BLOCKED, reason="End test after approved action.")]
            ),
        )
        context = runtime3.reconstruct(task_id)
        assert finished.status is TaskStatus.BLOCKED
        assert context.checkpoint is not None
        assert len(context.checkpoint.state["active_projects"]) == 1  # type: ignore[arg-type]
        types = [event.event_type for event in context.events]
        assert types.count(RuntimeEventType.APPROVAL_GRANTED) == 1
        assert types.count(RuntimeEventType.ACTION_EXECUTED) == 1
        engine3.dispose()

    asyncio.run(scenario())


def test_scenario_d_denied_approval_never_executes_after_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'denied.db'}"
        upgrade_database(url)
        task = approval_task()
        engine1, runtime1 = open_runtime(url)
        await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider([execute_build()]),
        )
        runtime1.deny(task.id)
        engine1.dispose()

        def forbidden_factory(context: ReconstructedRuntimeContext) -> NoReturn:
            del context
            raise AssertionError("terminal denial must not restore an adapter")

        engine2, runtime2 = open_runtime(url)
        outcome = await runtime2.resume(
            task.id,
            forbidden_factory,
            ScriptedDecisionProvider([]),
        )
        assert outcome.status is TaskStatus.BLOCKED
        assert all(
            event.event_type is not RuntimeEventType.ACTION_EXECUTED
            for event in runtime2.reconstruct(task.id).events
        )
        engine2.dispose()

    asyncio.run(scenario())


def test_scenario_e_cancellation_survives_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'cancelled.db'}"
        upgrade_database(url)
        task = make_task()
        engine1, runtime1 = open_runtime(url)
        runtime1.create_task(task)
        runtime1.cancel(task.id)
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        outcome = await runtime2.resume(
            task.id,
            lambda context: (_ for _ in ()).throw(AssertionError(context)),
            ScriptedDecisionProvider([]),
        )
        assert outcome.status is TaskStatus.CANCELLED
        assert runtime2.reconstruct(task.id).cancel_requested
        engine2.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("identifier", "decision", "expected"),
    [
        (501, None, TaskStatus.COMPLETED),
        (
            502,
            Decision(type=DecisionType.BLOCKED, reason="No path."),
            TaskStatus.BLOCKED,
        ),
    ],
)
def test_scenario_f_terminal_tasks_reopen_without_adapter_execution(
    tmp_path: Path,
    identifier: int,
    decision: Decision | None,
    expected: TaskStatus,
) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / f'terminal-{identifier}.db'}"
        upgrade_database(url)
        task = make_task(target=400_000 if decision is None else 1_000_000).model_copy(
            update={"id": UUID(int=identifier)}
        )
        engine1, runtime1 = open_runtime(url)
        provider = ScriptedDecisionProvider([] if decision is None else [decision])
        outcome = await runtime1.run(task, ReferenceSimulationAdapter(), provider)
        assert outcome.status is expected
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        reopened = await runtime2.resume(
            task.id,
            lambda context: (_ for _ in ()).throw(AssertionError(context)),
            ScriptedDecisionProvider([]),
        )
        assert reopened.status is expected
        engine2.dispose()

    asyncio.run(scenario())


def test_scenario_f_failed_task_reopens_without_adapter_execution(tmp_path: Path) -> None:
    class InitializationFailureAdapter(ReferenceSimulationAdapter):
        async def initialize(self) -> None:
            raise RuntimeError("initialization failed")

    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'terminal-failed.db'}"
        upgrade_database(url)
        task = make_task().model_copy(update={"id": UUID(int=503)})
        engine1, runtime1 = open_runtime(url)
        failed = await runtime1.run(
            task,
            InitializationFailureAdapter(),
            ScriptedDecisionProvider([]),
        )
        assert failed.status is TaskStatus.FAILED
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        reopened = await runtime2.resume(
            task.id,
            lambda context: (_ for _ in ()).throw(AssertionError(context)),
            ScriptedDecisionProvider([]),
        )
        assert reopened.status is TaskStatus.FAILED
        engine2.dispose()

    asyncio.run(scenario())


def test_scenario_g_failed_iteration_transaction_rolls_back(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'rollback.db'}"
        upgrade_database(url)
        task = make_task(target=1_000_000)
        engine1, runtime1 = open_runtime(url)
        await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider([]),
            iteration_budget=0,
        )
        before = runtime1.reconstruct(task.id)
        with engine1.begin() as connection:
            connection.execute(
                text(
                    """CREATE TRIGGER fail_verification BEFORE INSERT ON events
                    WHEN NEW.event_type = 'verification_recorded'
                    BEGIN SELECT RAISE(ABORT, 'injected persistence failure'); END"""
                )
            )
        adapter = ReferenceSimulationAdapter.from_snapshot(before.adapter_snapshot())
        with pytest.raises(DurablePersistenceError):
            await runtime1.run(
                before.task,
                adapter,
                ScriptedDecisionProvider([execute_advance()]),
                iteration_budget=1,
            )
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        after = runtime2.reconstruct(task.id)
        assert after.task.sequence > before.task.sequence
        assert after.task.total_spend == before.task.total_spend
        assert after.checkpoint == before.checkpoint
        assert after.events[: len(before.events)] == before.events
        assert after.unresolved_attempt is not None
        assert after.unresolved_attempt.status.value == "execution_started"
        engine2.dispose()

    asyncio.run(scenario())


def test_scenario_h_checkpoint_event_mismatch_fails_reconstruction(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'mismatch.db'}"
    upgrade_database(url)
    task = make_task()
    engine, runtime = open_runtime(url)
    runtime.create_task(task)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE tasks SET current_sequence = current_sequence + 1 WHERE id = :id"),
            {"id": str(task.id)},
        )
    with pytest.raises(ReconstructionConsistencyError, match="sequence"):
        runtime.reconstruct(task.id)
    engine.dispose()


def test_safeguard_counts_continue_across_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'safeguards.db'}"
        upgrade_database(url)
        task = make_task(target=1_000_000)
        wait = Decision(type=DecisionType.WAIT, reason="Wait.")
        engine1, runtime1 = open_runtime(url)
        partial = await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider([wait]),
            iteration_budget=1,
        )
        assert partial.status is TaskStatus.RUNNING
        assert runtime1.reconstruct(task.id).runtime_state.repeated_state_count == 1
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        outcome = await runtime2.resume(
            task.id,
            restore_reference,
            ScriptedDecisionProvider([wait, wait]),
        )
        assert outcome.status is TaskStatus.BLOCKED
        assert outcome.reason == "repeated state detected"
        engine2.dispose()

    asyncio.run(scenario())


def test_pause_and_resume_each_advance_the_durable_checkpoint(tmp_path: Path) -> None:
    async def scenario() -> None:
        url = f"sqlite:///{tmp_path / 'pause-resume.db'}"
        upgrade_database(url)
        task = make_task(target=1_000_000)
        pause = Decision(
            type=DecisionType.EXECUTE,
            reason="Pause.",
            action=make_action("pause"),
        )
        resume = Decision(
            type=DecisionType.EXECUTE,
            reason="Resume.",
            action=make_action("resume"),
        )
        engine1, runtime1 = open_runtime(url)
        await runtime1.run(
            task,
            ReferenceSimulationAdapter(),
            ScriptedDecisionProvider([pause]),
            iteration_budget=1,
        )
        paused = runtime1.reconstruct(task.id)
        assert paused.checkpoint is not None
        assert paused.checkpoint.state["paused"] is True
        paused_sequence = paused.checkpoint.metadata.runtime_sequence
        engine1.dispose()

        engine2, runtime2 = open_runtime(url)
        await runtime2.resume(
            task.id,
            restore_reference,
            ScriptedDecisionProvider([resume]),
            iteration_budget=1,
        )
        resumed = runtime2.reconstruct(task.id)
        assert resumed.checkpoint is not None
        assert resumed.checkpoint.state["paused"] is False
        assert resumed.checkpoint.metadata.runtime_sequence > paused_sequence
        engine2.dispose()

    asyncio.run(scenario())
