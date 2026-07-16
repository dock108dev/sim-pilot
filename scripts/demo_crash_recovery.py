"""Repeatable Task 4C crash-window demonstration."""

import asyncio
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    Task,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.persistence.sqlite import SQLiteUnitOfWork, create_sqlite_engine, upgrade_database
from sim_pilot.runtime import RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.action_attempts import RecoveryResolution
from sim_pilot.runtime.errors import SimulatedCrash
from sim_pilot.runtime.recovery import CrashPoint


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory) / 'crash-demo.db'}"
        upgrade_database(url)
        engine = create_sqlite_engine(url)

        def crash(point: CrashPoint) -> None:
            if point is CrashPoint.AFTER_EXECUTION:
                raise SimulatedCrash(point.value)

        runtime = RuntimeEngine(
            unit_of_work_factory=lambda: SQLiteUnitOfWork(engine), crash_hook=crash
        )
        now = datetime.now(UTC)
        task = Task(
            id=UUID("00000000-0000-0000-0000-000000000404"),
            status=TaskStatus.PENDING,
            specification=TaskSpecification(
                objective=Objective(
                    type=ObjectiveType.REACH_RESOURCE,
                    description="Reach one million cash.",
                    parameters={"resource": "cash", "target": 1_000_000},
                ),
                authority=AuthorityPolicy(),
            ),
            created_at=now,
            updated_at=now,
        )
        adapter = ReferenceSimulationAdapter()
        decision = Decision(
            type=DecisionType.EXECUTE,
            reason="Demonstrate interrupted execution.",
            action=Action(
                type="advance_time",
                parameters={"ticks": 1},
                expected_effect="Advance one simulation tick.",
            ),
        )
        with suppress(SimulatedCrash):
            await runtime.run(task, adapter, ScriptedDecisionProvider([decision]))
        current = adapter.snapshot()
        engine.dispose()

        restarted_engine = create_sqlite_engine(url)
        restarted = RuntimeEngine(unit_of_work_factory=lambda: SQLiteUnitOfWork(restarted_engine))
        report = await restarted.inspect_recovery(task.id, current)
        if report is None:
            raise RuntimeError("expected an interrupted action attempt")
        print(f"classification={report.classification.value}")
        await restarted.resolve_recovery(
            task.id, RecoveryResolution.MARK_EXECUTED, current_snapshot=current
        )
        context = restarted.reconstruct(task.id)
        print(f"resolved={context.unresolved_attempt is None}")
        checkpoint = context.checkpoint
        if checkpoint is None:
            raise RuntimeError("recovery did not create a checkpoint")
        print(f"tick={checkpoint.metadata.simulation_tick}")
        restarted_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
