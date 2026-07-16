"""Minimal durable Task 4C command-line interface."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID, uuid4

import typer
from pydantic import ValidationError
from sqlalchemy import Engine

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.config import database_url
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    Observation,
    Task,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.persistence import PersistenceError
from sim_pilot.persistence.sqlite import (
    SQLiteUnitOfWork,
    create_sqlite_engine,
    upgrade_database,
)
from sim_pilot.runtime import RuntimeEngine
from sim_pilot.runtime.action_attempts import RecoveryResolution
from sim_pilot.runtime.errors import DurablePersistenceError, ReconstructionConsistencyError
from sim_pilot.runtime.reconstruction import ReconstructedRuntimeContext

SUCCESS = 0
WAITING_APPROVAL = 10
RECOVERY_REQUIRED = 11
BLOCKED = 12
FAILED = 13
CANCELLED = 14
INVALID_INPUT = 20
PERSISTENCE_FAILURE = 21
MIGRATION_FAILURE = 22

app = typer.Typer(help="Durable local runtime for the deterministic reference simulation.")
db_app = typer.Typer(help="Manage durable schema state.")
task_app = typer.Typer(help="Create and operate structured tasks.")
recovery_app = typer.Typer(help="Inspect and resolve interrupted action attempts.")
app.add_typer(db_app, name="db")
app.add_typer(task_app, name="task")
task_app.add_typer(recovery_app, name="recovery")


@dataclass
class CLIContext:
    url: str


@app.callback()
def main(
    ctx: typer.Context,
    database: Annotated[
        str | None,
        typer.Option("--database", help="SQLite URL or database file path."),
    ] = None,
) -> None:
    ctx.obj = CLIContext(database_url(database))


def _context(ctx: typer.Context) -> CLIContext:
    return ctx.ensure_object(CLIContext)


def _runtime(ctx: typer.Context) -> tuple[Engine, RuntimeEngine]:
    engine = create_sqlite_engine(_context(ctx).url)
    return engine, RuntimeEngine(unit_of_work_factory=lambda: SQLiteUnitOfWork(engine))


def _restore(context: ReconstructedRuntimeContext) -> ReferenceSimulationAdapter:
    if context.checkpoint is None:
        return ReferenceSimulationAdapter()
    return ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot())


class ReferenceDemoDecisionProvider:
    async def decide(self, task: Task, observation: Observation) -> Decision:
        del task, observation
        return Decision(
            type=DecisionType.EXECUTE,
            reason="Advance the deterministic reference simulation.",
            action=Action(
                type="advance_time",
                parameters={"ticks": 1},
                expected_effect="Advance one simulation tick.",
            ),
        )


def _exit_for(status: TaskStatus, recovery: bool = False) -> int:
    if recovery:
        return RECOVERY_REQUIRED
    return {
        TaskStatus.WAITING_FOR_APPROVAL: WAITING_APPROVAL,
        TaskStatus.BLOCKED: BLOCKED,
        TaskStatus.FAILED: FAILED,
        TaskStatus.CANCELLED: CANCELLED,
    }.get(status, SUCCESS)


def _emit(value: object) -> None:
    if hasattr(value, "model_dump_json"):
        typer.echo(value.model_dump_json(indent=2))  # type: ignore[union-attr]
    else:
        typer.echo(json.dumps(value, indent=2, default=str))


def _fail(error: Exception, code: int = PERSISTENCE_FAILURE) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(code)


@db_app.command("upgrade")
def db_upgrade(ctx: typer.Context) -> None:
    try:
        upgrade_database(_context(ctx).url)
    except Exception as error:
        _fail(error, MIGRATION_FAILURE)
    typer.echo("database upgraded")


@task_app.command("create")
def task_create(
    ctx: typer.Context,
    specification: Annotated[
        Path | None, typer.Option("--spec", exists=True, dir_okay=False)
    ] = None,
    target_cash: Annotated[float, typer.Option(min=0)] = 520_000,
    task_id: Annotated[UUID | None, typer.Option()] = None,
) -> None:
    try:
        if specification is None:
            spec = TaskSpecification(
                objective=Objective(
                    type=ObjectiveType.REACH_RESOURCE,
                    description=f"Reach {target_cash:g} cash.",
                    parameters={"resource": "cash", "target": target_cash},
                ),
                authority=AuthorityPolicy(),
            )
        else:
            spec = TaskSpecification.model_validate_json(specification.read_text())
        now = datetime.now(UTC)
        task = Task(
            id=task_id or uuid4(),
            status=TaskStatus.PENDING,
            specification=spec,
            created_at=now,
            updated_at=now,
        )
        engine, runtime = _runtime(ctx)
        try:
            created = runtime.create_task(task)
        finally:
            engine.dispose()
        _emit(created)
    except (OSError, ValidationError, ValueError, PersistenceError) as error:
        _fail(error, INVALID_INPUT)


async def _run_task(ctx: typer.Context, task_id: UUID, iterations: int | None) -> int:
    engine, runtime = _runtime(ctx)
    try:
        outcome = await runtime.resume(
            task_id,
            _restore,
            ReferenceDemoDecisionProvider(),
            iteration_budget=iterations,
        )
        context = runtime.reconstruct(task_id)
        _emit(outcome)
        return _exit_for(outcome.status, context.unresolved_attempt is not None)
    finally:
        engine.dispose()


@task_app.command("run")
def task_run(
    ctx: typer.Context,
    task_id: UUID,
    iterations: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    try:
        code = asyncio.run(_run_task(ctx, task_id, iterations))
    except (PersistenceError, DurablePersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    raise typer.Exit(code)


@task_app.command("resume")
def task_resume(
    ctx: typer.Context,
    task_id: UUID,
    iterations: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    task_run(ctx, task_id, iterations)


@task_app.command("show")
def task_show(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        context = runtime.reconstruct(task_id)
        _emit(
            {
                "task": context.task.model_dump(mode="json"),
                "checkpoint": (
                    None
                    if context.checkpoint is None
                    else context.checkpoint.model_dump(mode="json")
                ),
                "pending_approval": (
                    None
                    if context.pending_approval is None
                    else context.pending_approval.model_dump(mode="json")
                ),
                "recovery": (
                    None
                    if context.unresolved_attempt is None
                    else context.unresolved_attempt.model_dump(mode="json")
                ),
            }
        )
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("events")
def task_events(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        for event in runtime.reconstruct(task_id).events:
            typer.echo(event.model_dump_json())
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


def _approval_task_id(ctx: typer.Context, approval_id: UUID) -> UUID:
    engine = create_sqlite_engine(_context(ctx).url)
    task_id: UUID | None = None
    try:
        with SQLiteUnitOfWork(engine) as uow:
            task_id = uow.approvals.get(approval_id).approval.task_id
    finally:
        engine.dispose()
    if task_id is None:
        raise RuntimeError("approval lookup returned no task")
    return task_id


@task_app.command("approve")
def task_approve(ctx: typer.Context, approval_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        approved = runtime.approve(_approval_task_id(ctx, approval_id))
        _emit(approved)
    except (PersistenceError, ValueError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("deny")
def task_deny(ctx: typer.Context, approval_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        denied = runtime.deny(_approval_task_id(ctx, approval_id))
        _emit(denied)
    except (PersistenceError, ValueError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


@task_app.command("cancel")
def task_cancel(ctx: typer.Context, task_id: UUID) -> None:
    engine, runtime = _runtime(ctx)
    try:
        runtime.cancel(task_id)
        typer.echo("task cancelled")
    except (PersistenceError, ReconstructionConsistencyError) as error:
        _fail(error)
    finally:
        engine.dispose()


def _snapshot(path: Path | None) -> AdapterSnapshot | None:
    return None if path is None else AdapterSnapshot.model_validate_json(path.read_text())


@recovery_app.command("show")
def recovery_show(
    ctx: typer.Context,
    task_id: UUID,
    snapshot: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    engine, runtime = _runtime(ctx)
    try:
        report = asyncio.run(runtime.inspect_recovery(task_id, _snapshot(snapshot)))
        _emit({"recovery": None} if report is None else report)
    except (OSError, ValidationError, ValueError, PersistenceError) as error:
        _fail(error)
    finally:
        engine.dispose()


@recovery_app.command("resolve")
def recovery_resolve(
    ctx: typer.Context,
    task_id: UUID,
    resolution: RecoveryResolution,
    snapshot: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    engine, runtime = _runtime(ctx)
    try:
        asyncio.run(
            runtime.resolve_recovery(task_id, resolution, current_snapshot=_snapshot(snapshot))
        )
        typer.echo("recovery resolved")
    except (OSError, ValidationError, ValueError, PersistenceError) as error:
        _fail(error)
    finally:
        engine.dispose()
