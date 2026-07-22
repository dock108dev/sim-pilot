# SSOT Enforcement

## Status

Implemented on 2026-07-19 and re-audited on 2026-07-20. This document records the supported
authority boundaries after the security, abend-hardening, and read-only intelligence passes.

## Authoritative paths

| Domain | Source of truth | Current callers and boundary |
|---|---|---|
| Domain contracts | `sim_pilot.domain.models` and `sim_pilot.domain.types` | Runtime, compiler, adapters, persistence, and CLI use the same strict Pydantic models. `TaskSpecification.adapter_type` accepts only `reference` or `openttd`. |
| Configuration | `sim_pilot.config` | CLI composition, hosted-provider composition, and Alembic resolve supported environment settings here. |
| Capability selection | `sim_pilot.intent_compiler.prompt.capability_catalog` | CLI and product evaluation select the reference or OpenTTD catalog through one fail-closed router. |
| Intent validation | `sim_pilot.intent_compiler.compiler.IntentCompiler` and `sim_pilot.intent_compiler.validation` | Provider output is untrusted until deterministic catalog validation succeeds. |
| Provider telemetry | `sim_pilot.provider_metadata` | Compiler and decision providers share `ProviderMetadata` and `ProviderTokenUsage` directly. |
| Runtime lifecycle | `sim_pilot.runtime.engine.RuntimeEngine` | CLI and tests use the stable facade. Execution, one-cycle iteration, crash-journaled action execution, and pure helpers live in dedicated `runtime` modules behind it. |
| Adapter refresh policy | `SimulationAdapter.requires_fresh_observation_on_resume` and `AdapterValidation.state_stale` in `sim_pilot.adapters.base` | Every runtime adapter and validation result must state these policies explicitly. Runtime execution and iteration consume the typed values directly; an incomplete adapter can no longer inherit a silent `False` fallback. |
| Reference simulation | `sim_pilot.reference_simulation` | `ReferenceSimulationAdapter` wraps the standalone deterministic state machine. |
| OpenTTD integration | `sim_pilot.adapters.openttd.OpenTTDAdapter` | Read-only and explicitly enabled write behavior use one adapter; there is no separate read-only class alias. |
| OpenTTD bridge protocol | `sim_pilot.openttd.gamescript.models` and `sim_pilot.openttd.gamescript.client` | The distributed GameScript, client parser, protocol negotiation, sequence checks, and resynchronization tests define the proven bridge boundary. Unsupported bridge messages and capabilities fail closed. |
| Game-neutral bridge protocol | `sim_pilot.game_bridge.models` and `sim_pilot.game_bridge.client` | Strict protocol v1 envelopes, authenticated loopback framing, sequencing, identity, full snapshots, and resynchronization. It grants no gameplay authority. |
| Rail Route bridge lifecycle | `sim_pilot.rail_route.bridge` plus `rail_route_bridge/` | Exact compatibility diagnosis, manifest-owned loader install/disable/uninstall, and game-side read-only translation remain separate from screen control and the persisted action runtime. |
| Persistence contracts | `sim_pilot.persistence.repositories` and `sim_pilot.persistence.unit_of_work` | Runtime depends on repository and unit-of-work interfaces. SQLite implementations remain below that boundary. |
| Schema and database selection | Alembic migrations plus `sim_pilot.config.database_url` | Application and raw Alembic commands share URL resolution. Explicit programmatic migration URLs override the environment. |
| Recovery dispatch | `sim_pilot.reconciliation.composition.default_reconciliation_dispatcher` | Persisted adapter type chooses exactly one reconciler; unknown and mismatched types fail closed. |
| Product-evaluation review | `ProductEvaluationResult` in `sim_pilot.product_evaluation` | Compiler, decision, runtime, and overall ratings are canonical. The old aggregate `manual_rating` is accepted only while loading existing local artifacts and is migrated to `overall_rating`. |
| Gameplay analysis contracts | `sim_pilot.analysis.contracts` | Analyzers, interaction composition, session persistence, rendering, and JSON output share strict request, finding, presentation, guidance, and snapshot-provenance models. |
| Analysis orchestration | `sim_pilot.analysis.service.AnalysisService` | CLI entry points and contextual follow-ups invoke the same deterministic analyzers and optional explanation boundary. |
| Inspection guidance | `sim_pilot.analysis.inspection` | Typed guidance is derived from deterministic finding evidence, rendered in one place, and checked against the compact interaction budget. |
| Snapshot compatibility and freshness | `sim_pilot.analysis.freshness` plus `AnalysisResponse.snapshot_metadata` | Cache lookup verifies world, save generation, company, bridge generation/synchronization, and capability fingerprint. The canonical response metadata is the only freshness source used by detailed and JSON rendering. |
| Analysis-session retention | `sim_pilot.analysis.session.AnalysisSessionStore` | Current answers and snapshots are retained for evidence drill-down, contextual follow-ups, and explicit entity-inspection references. Bounded loaders normalize only the documented older local record shapes. |
| Named-entity inspection | `sim_pilot.analysis.entity_inspection` | Explicit commands validate analysis, finding, entity, world, and snapshot identity. The current proven OpenTTD boundary returns `unsupported`; it does not simulate an unverifiable viewport action. |

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
- Removed the renderer's unused `snapshot_age_seconds` and `cached` inputs. Detailed and JSON output
  now consume only the canonical `AnalysisResponse.snapshot_metadata` populated by analysis
  orchestration.
- Replaced runtime `getattr(..., False)` fallbacks for observation refresh and stale validation with
  required typed adapter policy. The reference and OpenTTD adapters state their differing behavior
  explicitly.

## Retained compatibility boundary

One ignored local founder-test database contains a pre-7.6 checkpoint whose adapter identifier is
`sim_pilot.adapters.openttd.adapter.OpenTTDAdapter`. Its task specification already uses canonical
`openttd`. The reconciliation dispatcher therefore retains that exact identifier as a bounded
read-compatibility registration that routes to the canonical OpenTTD reconciler. New specifications
cannot emit it, and no general alias or fallback is accepted. Removing it requires an explicit
checkpoint data migration rather than a source-only cleanup.

Two current CLI switches intentionally overlap in one narrow case: `--live` preserves the existing
live-source selection contract, while `--fresh` is the explicit cache-bypass control added for
freshness-sensitive callers. Both route to the same acquisition policy and neither creates an
alternate collector.

Protocol-v1 bridge parsing, older analysis-session normalization, and product-evaluation
`manual_rating` loading remain bounded read compatibility for existing local evidence. Current
writes emit only protocol v2, current analysis records, and `overall_rating`. Removing these readers
requires a deliberate migration or retirement of the corresponding local artifacts.

## Enforcement

Tests reject unknown task adapter types and capability catalogs, assert that removed public aliases
stay absent, require explicit adapter refresh/staleness policy, and prevent parallel renderer
freshness inputs from returning. They also verify current evaluation output omits `manual_rating`
and prove raw Alembic honors `SIM_PILOT_DATABASE` while explicit programmatic URLs win. Unknown
recovery identifiers, snapshot identity mismatches, corrupt cache entries, and unsupported
inspection actions continue to fail closed.
