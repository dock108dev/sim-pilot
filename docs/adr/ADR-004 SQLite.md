# ADR-004: SQLite Persistence

- Status: Accepted
- Date: 2026-07-16

## Context

Sim Pilot is a local, single-runtime application that must persist ordered task lifecycle events,
observations, tasks, and approvals and restore them after restart.

## Decision

Use SQLite as the persistence database. Store versioned domain payloads and preserve event sequence
ordering transactionally. The exact schema and whether access uses direct SQL or a lightweight
mapping layer will be decided with the persistence vertical slice.

## Consequences

The application needs no external database service and can use transactions and durable local
files. SQLite concurrency limits are acceptable under the single-runtime assumption. Storage API
and migration mechanics remain deliberate future decisions rather than foundation behavior.
