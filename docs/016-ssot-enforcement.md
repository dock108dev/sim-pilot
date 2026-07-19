# SSOT Enforcement

## Status

Implemented on 2026-07-19. This document records the supported authority boundaries after the
security and abend-hardening passes.

## Authoritative paths

| Domain | Source of truth | Current callers and boundary |
|---|---|---|
| Domain contracts | `sim_pilot.domain.models` and `sim_pilot.domain.types` | Runtime, compiler, adapters, persistence, and CLI use the same strict Pydantic models. `TaskSpecification.adapter_type` accepts only `reference` or `openttd`. |
| Configuration | `sim_pilot.config` | CLI composition, hosted-provider composition, and Alembic resolve supported environment settings here. |
| Capability selection | `sim_pilot.intent_compiler.prompt.capability_catalog` | CLI and product evaluation select the reference or OpenTTD catalog through one fail-closed router. |
| Intent validation | `sim_pilot.intent_compiler.compiler.IntentCompiler` and `sim_pilot.intent_compiler.validation` | Provider output is untrusted until deterministic catalog validation succeeds. |
| Provider telemetry | `sim_pilot.provider_metadata` | Compiler and decision providers share `ProviderMetadata` and `ProviderTokenUsage` directly. |
| Runtime lifecycle | `sim_pilot.runtime.engine.RuntimeEngine` | CLI and tests use the stable facade. Execution, one-cycle iteration, crash-journaled action execution, and pure helpers live in dedicated `runtime` modules behind it. |
| Reference simulation | `sim_pilot.reference_simulation` | `ReferenceSimulationAdapter` wraps the standalone deterministic state machine. |
| OpenTTD integration | `sim_pilot.adapters.openttd.OpenTTDAdapter` | Read-only and explicitly enabled write behavior use one adapter; there is no separate read-only class alias. |
| Persistence contracts | `sim_pilot.persistence.repositories` and `sim_pilot.persistence.unit_of_work` | Runtime depends on repository and unit-of-work interfaces. SQLite implementations remain below that boundary. |
| Schema and database selection | Alembic migrations plus `sim_pilot.config.database_url` | Application and raw Alembic commands share URL resolution. Explicit programmatic migration URLs override the environment. |
| Recovery dispatch | `sim_pilot.reconciliation.composition.default_reconciliation_dispatcher` | Persisted adapter type chooses exactly one reconciler; unknown and mismatched types fail closed. |
| Product-evaluation review | `ProductEvaluationResult` in `sim_pilot.product_evaluation` | Compiler, decision, runtime, and overall ratings are canonical. The old aggregate `manual_rating` is accepted only while loading existing local artifacts and is migrated to `overall_rating`. |

## Removed or routed constructs

- Removed the unused `AppConfiguration` aggregate. Typed configuration functions are the supported
  access path.
- Removed `OpenTTDReadOnlyAdapter`; all OpenTTD callers now use `OpenTTDAdapter`, whose configured
  write permissions determine available behavior.
- Removed compiler-specific aliases for provider metadata and token usage. Compiler providers now
  import the shared telemetry models directly.
- Replaced reference-defaulting catalog selection with `capability_catalog`, which rejects unknown
  adapter types.
- Replaced catch-all provider branches with explicit `none`, `scripted`, `codex`, and `openai`
  handling as applicable.
- Removed `manual_rating` from current evaluation output. Existing artifacts are normalized at the
  file boundary without creating a second live rating policy.
- Routed raw Alembic database selection through the same configuration function used by the CLI.

## Retained compatibility boundary

One ignored local founder-test database contains a pre-7.6 checkpoint whose adapter identifier is
`sim_pilot.adapters.openttd.adapter.OpenTTDAdapter`. Its task specification already uses canonical
`openttd`. The reconciliation dispatcher therefore retains that exact identifier as a bounded
read-compatibility registration that routes to the canonical OpenTTD reconciler. New specifications
cannot emit it, and no general alias or fallback is accepted. Removing it requires an explicit
checkpoint data migration rather than a source-only cleanup.

## Enforcement

Tests reject unknown task adapter types and capability catalogs, assert that removed public aliases
stay absent, verify current evaluation output omits `manual_rating`, and prove raw Alembic honors
`SIM_PILOT_DATABASE` while explicit programmatic URLs win. Unknown recovery identifiers continue to
fail closed.
