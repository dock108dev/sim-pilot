# ADR-004: SQLite Persistence

- Status: Accepted
- Date: 2026-07-16

## Context

Sim Pilot is a local, single-runtime application that must persist ordered task lifecycle events,
observations, tasks, and approvals and restore them after restart.

## Decision

Use SQLite as the durable persistence database in Task 4. Store versioned domain payloads and
preserve event sequence ordering transactionally. Task 3 first defines the storage interface and
runtime semantics using an append-only in-memory event store. The exact SQLite schema and whether
access uses direct SQL or a lightweight mapping layer will be decided with the Task 4 persistence
vertical slice.

## Consequences

The application needs no external database service and can use transactions and durable local
files. SQLite concurrency limits are acceptable under the single-runtime assumption. Runtime code
must not depend on SQLite directly; the Task 4 implementation replaces the Task 3 in-memory store
behind the same interface.
