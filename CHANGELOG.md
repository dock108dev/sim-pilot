# Changelog

All notable changes to Sim Pilot are documented in this file.

## Unreleased

### Product evaluation corrections

- Recorded the first 31-case live-model baseline and prepared the founder usage checklist.
- Corrected project-completion evidence and already-satisfied run-until handling.
- Split manual evaluation ratings across compiler, decision, runtime, and overall behavior.
- Advanced the compiler prompt to `intent-compiler-v3` for required/forbidden method conflicts,
  percent-like maintenance ambiguity, and valid passive OpenTTD monitoring shapes.

### Codex CLI local provider

- Added explicitly selected Codex CLI compiler and decision providers backed by authenticated
  `codex exec`, with no `OPENAI_API_KEY` or direct OpenAI API call.
- Added non-billable capability probing, isolated ephemeral read-only subprocess execution, strict
  structured output, bounded JSONL telemetry, typed failures, and opt-in sanitized diagnostics.
- Added Codex product-evaluation support with call and wall-clock limits, resumable cases, and
  allowance-aware reporting that does not fabricate API cost.
- Normal defaults and CI remain network-free; live Codex tests require separate opt-in flags and
  explicit owner authorization.

## 0.1.0 — 2026-07-19

Initial product-prototype baseline.

### Runtime and domain

- Added strict, versioned Pydantic domain models and public task, observation,
  action, decision, and execution-result contracts.
- Added the deterministic reference simulation with economic progression,
  projects, validation, failure behavior, fixtures, and snapshot restoration.
- Added the one-action-per-cycle runtime with progress evaluation, policy,
  approvals, deterministic verification, safeguards, and lifecycle events.

### Persistence and recovery

- Added SQLite persistence behind repository and unit-of-work interfaces.
- Added Alembic migrations, atomic iteration commits, append-only event history,
  checkpoints, process-level resume, approval recovery, and crash-window action
  reconciliation.
- Ambiguous external action outcomes require manual recovery; Sim Pilot does not
  claim exactly-once execution.

### Model-backed behavior

- Added the natural-language Intent Compiler with strict structured output,
  environment-specific capability catalogs, deterministic semantic validation,
  scripted fixtures, and optional secure request recordings.
- Added the model-backed runtime Decision Provider with bounded context,
  deterministic validation, typed provider failures, optional recordings, and
  an offline-safe default.
- Hosted OpenAI calls always require explicit provider selection and independent
  API credentials; CI never requires paid calls.

### OpenTTD 15.3

- Added the loopback-only Admin Network protocol v3 client and typed company,
  economy, map, vehicle, station, and server observations.
- Added the opt-in `set_server_name` RCON action with reconnect-based independent
  verification.
- Added the production `SimPilotBridge` GameScript protocol v1 with strict
  negotiation, full snapshots, heartbeat, resynchronization, persisted script
  identity, save/load continuity, and a bounded command ledger.
- Added the separately gated `set_company_name` action with test-mode validation,
  correlation, duplicate handling, a fresh snapshot, and combined-state
  verification.

### Current limitations

- OpenTTD construction, route planning, vehicle control, generalized events,
  state deltas, authoritative restore, and public multiplayer automation are not
  supported.
- The GameScript bridge supports only OpenTTD 15.3, GameScript API 15, bridge
  protocol v1, and the exact `openttd-gamescript-v1` adapter contract.
- The product surface is a local CLI. There is no desktop UI, worker service,
  multi-task scheduler, consumer installer, or remote hosted service.
