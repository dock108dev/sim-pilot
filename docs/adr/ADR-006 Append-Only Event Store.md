# ADR-006: Append-Only In-Memory Event Store for Task 3

- Status: Accepted
- Date: 2026-07-16

## Context

Task 3 must establish runtime behavior for task lifecycle, ordered events, action verification,
completion, approval suspension, blocked states, and restart boundaries. Implementing SQLite at the
same time would couple runtime semantics to storage mechanics before those semantics are stable.

## Decision

Define an event-store interface and use an append-only in-memory implementation in Task 3. Runtime
events are immutable, versioned, scoped to a task, and assigned monotonically increasing sequence
numbers. Existing events cannot be updated, deleted, or inserted out of sequence.

The runtime depends only on the event-store interface. The in-memory implementation does not claim
durability across process restarts; Task 3 establishes the data and restoration boundaries at the
interface level. Task 4 replaces the implementation with SQLite without changing runtime behavior.

## Consequences

Task 3 can test lifecycle and replay behavior quickly and deterministically. Restart tests can use
a newly constructed runtime over an already populated store instance, but process-level durability
is deferred. SQLite schema, transactions, and migrations remain Task 4 concerns.
