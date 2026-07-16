# Sim Pilot

Sim Pilot is a local runtime for translating natural-language objectives into validated actions
against deterministic simulations. The repository contains typed domain models, the standalone
deterministic reference simulation, a deterministic runtime slice, and Task 4A SQLite persistence
infrastructure. Runtime checkpoint integration, process-level resume, LLM integration, and
natural-language compilation remain later milestones.

Every serialized domain model carries `schema_version`, currently `1`. Changes to
`TaskSpecification`, `Observation`, `Action`, or `Decision` require an accompanying RFC update.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12 (uv can install and manage it automatically)

The project does not depend on a `python` command being available. Use `uv run` for project
commands. On machines that expose Python through `py`, the equivalent direct interpreter command
is `py -3.12`, but it is not needed for the setup below.

## Local setup

```bash
uv python install 3.12
uv sync --dev
```

## Validation

Run the same checks used by GitHub Actions:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

To apply formatting locally:

```bash
uv run ruff format .
```

## Package layout

The public Python package is `sim_pilot`. Domain models are exported from `sim_pilot.domain` and
the package root. The standalone deterministic engine lives in `sim_pilot.reference_simulation`.
Its runtime-facing wrapper lives in `sim_pilot.adapters.reference`. Storage-independent contracts
and records live in `sim_pilot.persistence`; SQLite code is isolated below
`sim_pilot.persistence.sqlite`.

Dependency direction is `CLI -> Runtime -> Domain <- Adapter -> Reference Simulation`. Adapters
may import domain and standalone simulation types, but must not import runtime modules. The
reference simulation must not import adapters or runtime modules.

## Reference simulation

The deterministic engine is directly testable without the runtime:

```bash
uv run pytest tests/reference_simulation
uv run pytest tests/adapters/test_reference_adapter.py
```

Construct and execute a typed action:

```python
from sim_pilot.reference_simulation import AdvanceTime, ReferenceSimulation

simulation = ReferenceSimulation(seed=0)
result = simulation.execute(AdvanceTime(ticks=1))

assert result.success
print(simulation.state.model_dump_json(indent=2))
```

`ReferenceSimulation.to_json()` serializes state and `ReferenceSimulation.from_json()` restores it.
Canonical state inputs live under `tests/fixtures`.

## Deterministic runtime

Task 3 runs structured tasks through the reference adapter with a scripted decision provider:

```python
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

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
from sim_pilot.runtime import RuntimeEngine, ScriptedDecisionProvider

now = datetime.now(UTC)
task = Task(
    id=uuid4(),
    status=TaskStatus.PENDING,
    specification=TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach 520000 cash.",
            parameters={"resource": "cash", "target": 520000},
        ),
        authority=AuthorityPolicy(),
    ),
    created_at=now,
    updated_at=now,
)
advance = Action(
    type="advance_time",
    parameters={"ticks": 1},
    expected_effect="Advance one simulation tick.",
)
provider = ScriptedDecisionProvider(
    [Decision(type=DecisionType.EXECUTE, reason="Advance.", action=advance)] * 10
)
engine = RuntimeEngine()
outcome = asyncio.run(engine.run(task, ReferenceSimulationAdapter(), provider))

print(outcome.status)
print(engine.event_store.list_events(task.id))
```

## Runtime persistence roadmap

Task 3 uses an append-only in-memory event store and establishes runtime semantics without database
mechanics. Durable Task 4 persistence uses SQLite with current task and simulation snapshots plus
the complete event log. A restart loads snapshots directly rather than replaying every event.

Runtime code sees only `TaskRepository`, `EventRepository`, `ApprovalRepository`, and
`SimulationRepository`; SQLite stays below those interfaces. One runtime iteration commits its
task, simulation, approval, and event changes atomically. Alembic owns schema migrations from the
initial revision.

Task 4 is split into:

- 4A: persistence schema, repositories, migrations, and transactions
- 4B: checkpointing, restoration, and resume
- 4C: crash recovery, approval recovery, integration tests, and CLI wiring

## SQLite database and migrations

Alembic owns the durable schema. The checked-in default database URL is
`sqlite:///data/sim-pilot.db`; local database files under `data/` are ignored by Git.

Create or upgrade the local schema:

```bash
uv run alembic upgrade head
uv run alembic current
```

Downgrade one revision when explicitly testing migration reversal:

```bash
uv run alembic downgrade -1
```

Application code must not call `metadata.create_all()` or issue ad hoc production DDL. Tests use a
temporary path and invoke Alembic programmatically:

```python
from pathlib import Path

from sim_pilot.persistence.sqlite import (
    SQLiteUnitOfWork,
    create_sqlite_engine,
    upgrade_database,
)

database_url = f"sqlite:///{Path('/tmp') / 'sim-pilot-test.db'}"
upgrade_database(database_url)
engine = create_sqlite_engine(database_url)

with SQLiteUnitOfWork(engine) as uow:
    tasks = uow.tasks.list()
```

Repository consumers depend on `TaskRepository`, `EventRepository`, `ApprovalRepository`, and
`SimulationRepository`, never SQLAlchemy, SQLite connections, or Alembic. A `UnitOfWork` exposes
all four repositories on one transaction. Exiting its context commits on success and rolls back on
an exception, so a future runtime iteration can atomically persist its task snapshot, events,
approval changes, and simulation checkpoint.

Task 4A establishes this persistence capability only. The current runtime still uses its Task 3
in-memory state; checkpoint writes, restoration, resume, crash reconciliation, and persistence CLI
commands remain Task 4B/4C work.
