# ADR-004: SQLite Persistence

- Status: Accepted
- Date: 2026-07-16

## Context

Sim Pilot is a local, single-runtime application that must persist ordered task lifecycle events,
observations, tasks, and approvals and restore them after restart.

## Decision

Use SQLite as the durable persistence database in Task 4. Store versioned domain payloads and
preserve event sequence ordering transactionally. Task 3 first defines the storage interface and
runtime semantics using an append-only in-memory event store. Durable persistence uses current-state
snapshots plus the complete append-only event log. Alembic manages every schema version beginning
with the initial schema. ADR-007 defines repository ownership, transactions, recovery, and delivery
sequencing.

## Consequences

The application needs no external database service and can use transactions and durable local
files. SQLite concurrency limits are acceptable under the single-runtime assumption. Runtime code
must not depend on SQLite directly; the Task 4 implementation replaces the Task 3 in-memory store
behind repository interfaces. One runtime iteration is the atomic persistence unit.
