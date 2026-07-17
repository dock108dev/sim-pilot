# Sim Pilot

Sim Pilot is a local runtime for translating natural-language objectives into validated actions
against deterministic simulations. The repository contains typed domain models, the standalone
deterministic reference simulation, a deterministic runtime, durable SQLite checkpointing,
process-level resume, crash-window reconciliation, a versioned natural-language Intent Compiler,
and a durable CLI. Runtime decision making remains scripted; hosted model use is limited to intent
translation.

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

Execution dependency direction is `CLI -> Runtime -> Domain <- Adapter -> Reference Simulation`.
Compilation is `CLI -> Intent Compiler -> CompilerProvider`, with compiler output validated into
Domain. Only the OpenAI provider imports its SDK. Adapters may import domain and standalone
simulation types, but must not import runtime modules. The reference simulation must not import
adapters or runtime modules.

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

The runtime defaults to transactional in-memory repositories and accepts a `UnitOfWork` factory for
SQLite or test-specific storage. Durable persistence uses current task and simulation snapshots
plus the complete event log. A restart loads snapshots directly rather than replaying events to
rebuild simulation state.

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

## Programmatic restart and resume

Task 4B checkpoints the initial observation, every verified state-changing action, and initialized
terminal states. The example below runs one committed iteration, closes every database-backed
object, then reconstructs and resumes with fresh objects:

```python
database_url = "sqlite:///data/sim-pilot.db"
upgrade_database(database_url)

first_engine = create_sqlite_engine(database_url)
first_runtime = RuntimeEngine(
    unit_of_work_factory=lambda: SQLiteUnitOfWork(first_engine)
)
partial = asyncio.run(
    first_runtime.run(
        task,
        ReferenceSimulationAdapter(),
        provider,
        iteration_budget=1,
    )
)
first_engine.dispose()

second_engine = create_sqlite_engine(database_url)
second_runtime = RuntimeEngine(
    unit_of_work_factory=lambda: SQLiteUnitOfWork(second_engine)
)

def restore_reference(context):
    if context.checkpoint is None:
        return ReferenceSimulationAdapter()
    return ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot())

remaining_provider = ScriptedDecisionProvider(
    [Decision(type=DecisionType.EXECUTE, reason="Advance.", action=advance)] * 9
)
outcome = asyncio.run(
    second_runtime.resume(task.id, restore_reference, remaining_provider)
)
second_engine.dispose()
```

`resume` returns pending approvals and terminal tasks without initializing or executing an adapter.
Approval grants persist one exact action authorization across restart. Safeguard counters and
fingerprints also continue across processes. An atomic persistence failure rolls back task, event,
approval, and checkpoint writes and raises `DurablePersistenceError`.

## Durable CLI

### Natural-language compilation

Set an API key and optionally override the hosted compiler model:

```bash
export OPENAI_API_KEY="..."
export SIM_PILOT_COMPILER_MODEL="gpt-5.6"
```

Compile without persisting:

```bash
uv run sim-pilot task compile --instruction \
  'Run until cash reaches $1 million. Do not take loans. Keep at least $100,000 available. Ask before spending more than $50,000.'
```

Compile, review, confirm, and persist:

```bash
uv run sim-pilot --database /tmp/sim-pilot-demo.db task create --instruction \
  'Run until cash reaches $1 million. Do not take loans. Keep at least $100,000 available. Ask before spending more than $50,000.'
```

Omit `--instruction` from `task compile` for an interactive prompt. Use `--yes` with
`task create --instruction` only after accepting noninteractive persistence. Compiler output
includes assumptions, warnings, unsupported requests, ambiguities, deterministic validation
errors, and `prompt_version`. Only a `valid` compilation can be persisted.

Supported language covers all four RFC objectives, the five constraint types, notification and
stop conditions, per-action and total authority limits, approval actions, and all reference
simulation resources/actions. Missing material thresholds require clarification. Broad strategy,
optimization, action planning, and unsupported game capabilities are rejected.

Automated tests never make paid calls. To explicitly run the live structured-output test:

```bash
SIM_PILOT_LIVE_COMPILER=1 uv run pytest -m live \
  tests/intent_compiler/test_live_openai.py
```

### Persistence and runtime

All commands accept `--database PATH` before the command group. The same value may be supplied as
`SIM_PILOT_DATABASE`.

```bash
uv run sim-pilot --database /tmp/sim-pilot-demo.db db upgrade
uv run sim-pilot --database /tmp/sim-pilot-demo.db task create \
  --task-id 00000000-0000-0000-0000-000000000123 --target-cash 520000
uv run sim-pilot --database /tmp/sim-pilot-demo.db task run \
  00000000-0000-0000-0000-000000000123 --iterations 1
uv run sim-pilot --database /tmp/sim-pilot-demo.db task show \
  00000000-0000-0000-0000-000000000123
uv run sim-pilot --database /tmp/sim-pilot-demo.db task events \
  00000000-0000-0000-0000-000000000123
uv run sim-pilot --database /tmp/sim-pilot-demo.db task resume \
  00000000-0000-0000-0000-000000000123
```

`task create --spec task.json` accepts a serialized `TaskSpecification`. Without `--spec`, the
command creates the deterministic cash-target demo. Approval commands take an approval ID.
Recovery commands are:

```bash
uv run sim-pilot --database /tmp/sim-pilot-demo.db task recovery show TASK_ID
uv run sim-pilot --database /tmp/sim-pilot-demo.db task recovery resolve \
  TASK_ID mark_not_executed
```

`recovery show` accepts `--snapshot snapshot.json` when current adapter state is independently
observable. Without it, an interrupted in-process reference adapter is classified as
`adapter_unavailable`. Resolution never automatically retries the interrupted action.

Task exit codes are 0 for success or a committed slice, 10 for approval required, 11 for recovery
required, 12 for blocked, 13 for failed, 14 for cancelled, 20 for invalid input, 21 for persistence
or reconstruction failure, and 22 for migration failure.

## Crash-injection demonstration

```bash
uv run python scripts/demo_crash_recovery.py
```

The demonstration injects a stop after adapter execution, opens a fresh runtime over the same
SQLite database, classifies independently retained adapter state, and resolves the attempt without
retrying it. Crash hooks are test instrumentation and are not exposed by production CLI
composition. Sim Pilot does not claim exactly-once execution.
