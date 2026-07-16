# ADR-007: Durable Persistence Architecture

- Status: Accepted
- Date: 2026-07-16

## Context

Task 4 adds durable restart behavior after Task 3 established runtime semantics with an in-memory
event store. The design must preserve the complete audit log without forcing every restart to
replay the full history, keep SQLite out of runtime orchestration, and support schema evolution from
the first durable release.

## Decision

Use state snapshots plus an append-only event log, not event sourcing alone. Persist the current
task, current simulation state, approvals, and every runtime event. Restart loads the latest task
and simulation snapshots directly; the event stream remains available for audit and diagnostics but
is not required to reconstruct current state.

Treat one runtime iteration as the transaction boundary. All durable records representing that
iteration—including task updates, simulation checkpoint, approval changes, and new events—commit
atomically or not at all. Event sequences remain task-scoped and append-only.

Expose persistence only through four runtime-facing interfaces:

- `TaskRepository`
- `EventRepository`
- `ApprovalRepository`
- `SimulationRepository`

SQLite connections, SQL, tables, row mappings, and transaction mechanics stay beneath those
interfaces. A persistence unit of work coordinates the four repositories for an atomic iteration.

Use Alembic for schema migrations from the initial SQLite schema onward. Every schema change is a
versioned migration; application startup never invents or mutates schema ad hoc.

Deliver Task 4 in three increments:

- Task 4A: SQLite schema, repositories, Alembic migrations, and transaction tests; no runtime changes
- Task 4B: checkpoint save/restore and task resume; no CLI
- Task 4C: crash recovery, approval recovery, restart integration tests, and CLI wiring

## Consequences

Restarts are bounded by snapshot loading rather than event-history length, while the audit trail
remains complete. Runtime tests can substitute in-memory repositories without importing SQLite.
Repository contracts and transaction boundaries must be defined before runtime integration.

Adapter execution is an external side effect and cannot be rolled back by SQLite. A crash after an
action executes but before its checkpoint commits creates a reconciliation boundary. Task 4C must
detect and safely reconcile that case rather than assuming the database transaction can undo the
simulation action.
