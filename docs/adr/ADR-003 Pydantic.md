# ADR-003: Pydantic v2 Domain Boundaries

- Status: Accepted
- Date: 2026-07-16

## Context

The runtime will accept untrusted structured model output and exchange state across compiler,
runtime, adapter, and persistence boundaries. Those interfaces require deterministic validation
and serialization.

## Decision

Use strict Pydantic v2 models for domain boundaries. Reject unknown fields, validate invariants,
make observations immutable, and include `schema_version: int = 1` on every domain model.
`TaskSpecification`, `Observation`, `Action`, and `Decision` are public interfaces; changes require
an RFC update.

## Consequences

Invalid boundary data fails before execution and persisted payloads are versioned. Callers must
construct exact types because coercion is intentionally limited. Interface evolution carries a
documentation and migration obligation.
