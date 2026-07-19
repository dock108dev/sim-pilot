# Data and Persistence Model

Sim Pilot separates public domain data, runtime orchestration records, repository contracts, and
SQLite storage. Pydantic models validate the first three layers; SQLAlchemy Core describes the
database tables; Alembic owns schema changes.

## Public domain contracts

`src/sim_pilot/domain/models.py` is authoritative for serialized task and adapter data:

| Model | Role |
|---|---|
| `TaskSpecification` | Adapter, objective, constraints, authority, notifications, and stop conditions. |
| `Objective` / `Constraint` | Typed intent plus JSON-compatible parameters. |
| `AuthorityPolicy` | Per-action and total-spend limits plus approval and forbidden action sets. |
| `Observation` | Immutable observation sequence, capture timestamp, simulation tick, summary, and state. |
| `Action` | Proposed action, JSON-compatible parameters, expected effect, and estimated cost. |
| `Decision` | One execute, wait, complete, approval-required, or blocked decision. |
| `ExecutionResult` | Adapter-reported success, state-change flag, non-negative cost, and message. |
| `Task` | UUID, lifecycle status, specification, durable sequence/spend, and UTC timestamps. |

All domain models reject extra fields and carry `schema_version=1`. `TaskSpecification`,
`Observation`, `Action`, and `Decision` are versioned public interfaces: update the applicable RFC and
serialization tests when changing them. `ExecutionResult` currently has the four documented result
fields plus inherited `schema_version`; it has no optional error-code field.

`src/sim_pilot/domain/world.py` defines the immutable game-neutral world-observation contracts:
`WorldSnapshot`, metadata and capability coverage, companies, towns, industries, stations,
vehicles and orders, inferred routes, cargo flows, and discriminated world changes. OpenTTD wire
models never cross this boundary. The snapshot remains nested in the existing observation state,
so Phase 8A changes no persisted table or repository interface. See
[013-openttd-world-observation.md](013-openttd-world-observation.md).

## Runtime and repository records

`src/sim_pilot/runtime/models.py` defines strict runtime evaluations, policy decisions,
verification, approvals, safeguards, events, and outcomes. `runtime/action_attempts.py` contains the
crash journal used to distinguish prepared, started, confirmed, and unresolved external actions.

`src/sim_pilot/persistence/models.py` wraps those objects in storage-independent records:

- `TaskRecord` stores the current task, cancellation request, and safeguard counters.
- `EventRecord` gives each immutable sequenced runtime event a durable identity.
- `ApprovalRecord` stores pending or resolved authority decisions.
- `SimulationCheckpoint` stores a complete versioned adapter snapshot and restoration metadata.

Repository and unit-of-work protocols live above SQLite in `sim_pilot.persistence`. Both the
in-memory and SQLite implementations must satisfy the same repository contract tests.

## SQLite schema

The current Alembic head is `0002` and contains four tables:

| Table | Contents and invariants |
|---|---|
| `tasks` | Current task snapshot, specification JSON, runtime safeguards, sequence, spend, cancellation flag, and timestamps. |
| `events` | Append-only event JSON with a unique `(task_id, sequence)` ordering key. |
| `approvals` | Action JSON and resolution state; a partial unique index prevents duplicate pending approval for one serialized action. |
| `simulation_checkpoints` | State JSON and adapter restoration metadata, unique per `(task_id, runtime_sequence)`. |

Foreign keys cascade task deletion to dependent rows, although the current repositories expose no
task-delete operation. Decimal values and timestamps are serialized as text to preserve their
validated representation.

## Transactions and recovery

Each durable runtime boundary uses one unit of work, so its task mutation, ordered events, approval
change, and optional checkpoint become visible atomically. Action execution intentionally spans
three commits: the prepared journal event, the execution-started event, and the final verified
result plus checkpoint. External adapter execution cannot be part of a SQLite transaction, so
these committed boundaries make a crash classifiable and require reconciliation when its outcome
remains uncertain.

Sim Pilot uses snapshots plus the complete event log. Resume loads the latest task/checkpoint state
instead of replaying every event to rebuild simulation state; events remain available for audit and
consistency checks. This provides process-level resume, not exactly-once external execution.

## Migration workflow

```bash
export SIM_PILOT_DATABASE=/tmp/sim-pilot-schema.db
uv run sim-pilot db upgrade
uv run alembic current
```

Do not use `metadata.create_all()` for application schema management. Any persisted payload or
table change requires an Alembic migration plus compatibility and restart tests. The raw Alembic
CLI and application command share `SIM_PILOT_DATABASE`.
