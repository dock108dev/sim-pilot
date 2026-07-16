"""Task 4C crash-window, reconciliation, and manual recovery scenarios."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import Action, Decision, DecisionType, TaskStatus
from sim_pilot.persistence.sqlite import SQLiteUnitOfWork, create_sqlite_engine, upgrade_database
from sim_pilot.runtime import RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.action_attempts import (
    ActionAttempt,
    ActionAttemptStatus,
    ReconciliationClassification,
    RecoveryResolution,
    action_fingerprint,
)
from sim_pilot.runtime.errors import SimulatedCrash
from sim_pilot.runtime.recovery import CrashPoint, reconcile_reference_action
from tests.runtime.helpers import make_action, make_task


def _decision(action: Action) -> Decision:
    return Decision(type=DecisionType.EXECUTE, reason="Execute test action.", action=action)


def _runtime(
    path: Path, hook: Callable[[CrashPoint], None] | None = None
) -> tuple[Engine, RuntimeEngine]:
    url = f"sqlite:///{path}"
    upgrade_database(url)
    engine = create_sqlite_engine(url)
    runtime = RuntimeEngine(unit_of_work_factory=lambda: SQLiteUnitOfWork(engine), crash_hook=hook)
    return engine, runtime


def _crasher(target: CrashPoint):
    def crash(point: CrashPoint) -> None:
        if point is target:
            raise SimulatedCrash(point.value)

    return crash


@pytest.mark.parametrize(
    "point",
    (
        CrashPoint.BEFORE_EXECUTION,
        CrashPoint.AFTER_EXECUTION,
        CrashPoint.AFTER_OBSERVATION,
        CrashPoint.AFTER_VERIFICATION,
    ),
)
def test_incomplete_execution_boundaries_require_recovery(
    tmp_path: Path, point: CrashPoint
) -> None:
    async def scenario() -> None:
        engine, runtime = _runtime(tmp_path / f"{point.value}.db", _crasher(point))
        task = make_task(target=1_000_000)
        with pytest.raises(SimulatedCrash):
            await runtime.run(
                task,
                ReferenceSimulationAdapter(),
                ScriptedDecisionProvider([_decision(make_action("advance_time", ticks=1))]),
            )
        engine.dispose()

        engine2, runtime2 = _runtime(tmp_path / f"{point.value}.db")
        outcome = await runtime2.resume(
            task.id,
            lambda context: ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot()),
            ScriptedDecisionProvider([]),
        )
        context = runtime2.reconstruct(task.id)
        assert outcome.status is TaskStatus.RUNNING
        assert outcome.reason == "recovery intervention required"
        assert context.unresolved_attempt is not None
        assert context.unresolved_attempt.status is ActionAttemptStatus.RECONCILIATION_REQUIRED
        engine2.dispose()

    asyncio.run(scenario())


def test_prepared_attempt_is_safely_retired_and_committed_attempt_needs_no_recovery(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        for point, expected_recovery in (
            (CrashPoint.AFTER_PREPARED, False),
            (CrashPoint.AFTER_COMMIT, False),
        ):
            path = tmp_path / f"{point.value}.db"
            engine, runtime = _runtime(path, _crasher(point))
            task = make_task(target=1_000_000).model_copy(
                update={"id": UUID(int=1000 + len(point.value))}
            )
            with pytest.raises(SimulatedCrash):
                await runtime.run(
                    task,
                    ReferenceSimulationAdapter(),
                    ScriptedDecisionProvider([_decision(make_action("advance_time", ticks=1))]),
                )
            engine.dispose()
            engine2, runtime2 = _runtime(path)
            await runtime2.resume(
                task.id,
                lambda context: ReferenceSimulationAdapter.from_snapshot(
                    context.adapter_snapshot()
                ),
                ScriptedDecisionProvider(
                    [Decision(type=DecisionType.BLOCKED, reason="End recovery test.")]
                ),
            )
            context = runtime2.reconstruct(task.id)
            assert (context.unresolved_attempt is not None) is expected_recovery
            engine2.dispose()

    asyncio.run(scenario())


def test_adapter_unavailable_definite_and_ambiguous_classification(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "classify.db"
        adapter = ReferenceSimulationAdapter()
        engine, runtime = _runtime(path, _crasher(CrashPoint.AFTER_EXECUTION))
        task = make_task(target=1_000_000)
        with pytest.raises(SimulatedCrash):
            await runtime.run(
                task,
                adapter,
                ScriptedDecisionProvider([_decision(make_action("advance_time", ticks=1))]),
            )
        current = adapter.snapshot()
        unavailable = await runtime.inspect_recovery(task.id)
        definite = await runtime.inspect_recovery(task.id, current)
        assert unavailable is not None
        assert unavailable.classification is ReconciliationClassification.ADAPTER_UNAVAILABLE
        assert definite is not None
        assert definite.classification is ReconciliationClassification.DEFINITELY_EXECUTED
        ambiguous_state = dict(current.state)
        ambiguous_state["cash"] = 123.0
        ambiguous_state["tick"] = 99
        ambiguous = await runtime.inspect_recovery(
            task.id, current.model_copy(update={"state": ambiguous_state})
        )
        assert ambiguous is not None
        assert ambiguous.classification is ReconciliationClassification.AMBIGUOUS
        engine.dispose()

    asyncio.run(scenario())


def test_manual_mark_executed_checkpoints_and_accounts_cost_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "manual.db"
        adapter = ReferenceSimulationAdapter()
        engine, runtime = _runtime(path, _crasher(CrashPoint.AFTER_EXECUTION))
        task = make_task(target=1_000_000)
        with pytest.raises(SimulatedCrash):
            await runtime.run(
                task,
                adapter,
                ScriptedDecisionProvider([_decision(make_action("build_housing", units=10))]),
            )
        await runtime.resolve_recovery(
            task.id, RecoveryResolution.MARK_EXECUTED, current_snapshot=adapter.snapshot()
        )
        context = runtime.reconstruct(task.id)
        assert context.unresolved_attempt is None
        assert float(context.task.total_spend) == 10_000
        assert context.checkpoint is not None
        assert len(context.checkpoint.state["active_projects"]) == 1  # type: ignore[arg-type]
        engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("action", "parameters"),
    (
        ("advance_time", {"ticks": 1}),
        ("build_housing", {"units": 1}),
        ("build_power", {"capacity": 1}),
        ("repair", {"amount": 1.0}),
        ("set_maintenance", {"level": 1.0}),
        ("take_loan", {"amount": 10_000.0}),
        ("pause", {}),
    ),
)
def test_reference_replay_classifies_supported_action_effects(
    action: str, parameters: dict[str, object]
) -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()
        prior = adapter.snapshot()
        domain_action = Action(
            type=action,
            parameters=parameters,  # type: ignore[arg-type]
            expected_effect="Apply deterministic effect.",
        )
        attempt = ActionAttempt(
            task_id=UUID(int=1),
            runtime_sequence=1,
            action_id=UUID(int=2),
            action_fingerprint=action_fingerprint(domain_action),
            action=domain_action,
            prior_checkpoint_id=UUID(int=3),
            prior_observation_fingerprint="prior",
            expected_effect=domain_action.expected_effect,
            estimated_cost=0,
            status=ActionAttemptStatus.EXECUTION_STARTED,
            prepared_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await adapter.execute(domain_action)
        report = await reconcile_reference_action(attempt, prior, adapter.snapshot())
        assert report.classification is ReconciliationClassification.DEFINITELY_EXECUTED

    asyncio.run(scenario())


def test_repay_and_resume_reconciliation() -> None:
    async def scenario() -> None:
        for setup, action in (
            (make_action("take_loan", amount=10_000.0), make_action("repay_loan", amount=1.0)),
            (make_action("pause"), make_action("resume")),
        ):
            adapter = ReferenceSimulationAdapter()
            await adapter.initialize()
            await adapter.execute(setup)
            prior = adapter.snapshot()
            attempt = ActionAttempt(
                task_id=UUID(int=1),
                runtime_sequence=1,
                action_id=UUID(int=2),
                action_fingerprint=action_fingerprint(action),
                action=action,
                prior_checkpoint_id=UUID(int=3),
                prior_observation_fingerprint="prior",
                expected_effect=action.expected_effect,
                estimated_cost=0,
                status=ActionAttemptStatus.EXECUTION_STARTED,
                prepared_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await adapter.execute(action)
            report = await reconcile_reference_action(attempt, prior, adapter.snapshot())
            assert report.classification is ReconciliationClassification.DEFINITELY_EXECUTED

    asyncio.run(scenario())
