# ADR-005: Standalone Reference Simulation

- Status: Accepted
- Date: 2026-07-16

## Context

The deterministic simulation must be directly testable and reusable independently of runtime
orchestration. Placing simulation mechanics inside an adapter would couple the product behavior to
one integration boundary and encourage adapter-first design.

## Decision

Implement simulation state, economy, projects, tick transitions, actions, validation, and public
orchestration under `sim_pilot.reference_simulation`. Keep the runtime-facing wrapper under
`sim_pilot.adapters.reference`. The reference simulation must not import adapter or runtime
modules, and adapters must not import runtime modules.

## Consequences

Simulation behavior can be unit tested without the runtime and can gain other consumers later. The
adapter remains a translation layer over the engine rather than owning mechanics. Architecture
tests enforce both dependency restrictions.
