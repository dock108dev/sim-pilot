# Sim Pilot

Sim Pilot is a local runtime for translating natural-language objectives into validated actions
against deterministic simulations. The repository contains the Month 1 foundation, typed domain
models, and standalone deterministic reference simulation. The runtime engine, LLM integration,
and persistence are intentionally not implemented yet.

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
Its runtime-facing wrapper lives in `sim_pilot.adapters.reference`. The `runtime`, `llm`,
`persistence`, and `logging` subpackages remain foundation boundaries for later milestones.

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

Task 3 will use an append-only in-memory event store behind a storage interface. It establishes
ordered task lifecycle events, replay, action verification, completion, approval suspension,
blocked-state behavior, and restart boundaries without introducing database mechanics. Task 4 will
replace that implementation with SQLite without changing runtime behavior.
