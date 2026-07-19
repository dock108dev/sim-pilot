# ADR-008: Durable Action Attempt Journal and Reconciliation

- Status: Accepted
- Date: 2026-07-16

## Context

SQLite can atomically persist runtime records, but it cannot roll back an adapter side effect. A
process may stop after adapter execution and before the resulting observation and checkpoint are
committed. Retrying that action blindly can duplicate spending or state changes. ADR-007 also
limits runtime-facing persistence ownership to four repositories.

## Decision

Represent every external action attempt as a typed sequence in the existing append-only event
journal. Persist preparation and execution-start events before crossing the adapter boundary. On
success, atomically persist the result, post-action observation, verification, task and spend
updates, checkpoint, and attempt completion.

An attempt that entered execution but lacks completion prevents automatic runtime progress.
Reconciliation compares independently observed current adapter state with the prior checkpoint and
a deterministic replay. It classifies the attempt as definitely not executed, definitely executed,
inferable, ambiguous, or adapter unavailable. Ambiguous and unavailable outcomes require explicit
operator resolution; the runtime never automatically retries them.

Keep task status `running` while recovery is required. The unresolved durable attempt is the
recovery marker, avoiding a new public lifecycle state. Manual resolutions are accept current
state, mark executed, mark not executed, abandon, and restore the prior checkpoint. Crash hooks are
dependency-injected test instrumentation and are absent in normal composition.

## Consequences

The runtime retains ADR-007's four repository interfaces and gains a durable audit trail around the
external side-effect boundary. Sim Pilot does not claim exactly-once execution. An in-process
adapter whose uncheckpointed state disappears with the process cannot be independently reconciled
and is reported as adapter unavailable.

## Amendment: adapter-type dispatch

Phase 7.6 replaces action-name branching in the generic runtime with an injected reconciliation
registry keyed by the persisted adapter type. Adapter-specific reconcilers live in the application
composition layer, where they may depend on both runtime recovery records and adapter semantics;
neither the runtime nor adapter packages import each other to perform dispatch. Every supported
adapter identifier is registered explicitly, including a bounded compatibility alias for OpenTTD
checkpoints written before canonical `adapter_type="openttd"` snapshots. Unknown, duplicate, and
mismatched adapter registrations fail closed.
