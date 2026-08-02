# ADR-021: Software Inc. Read-Only Semantic Bridge

## Status

Accepted and live-proven for Phase 2 on macOS.

## Decision

Software Inc. uses Game Bridge Protocol v3 with adapter `software-inc-readonly-v1`, game version
`1.8.41`, and loopback port `18462`. The shared C# protocol/server receives an adapter contract;
Rail Route identity and surfaces are no longer compiled into the game-neutral core.

Software Inc. gameplay APIs are read only on Unity's main thread. Activation creates one dedicated,
active, non-gameplay `DontDestroyOnLoad` object with an enabled `SimPilotCapturePump`. A network request records one
pending capture and waits up to three seconds. The pump's Unity-owned `Update` callback performs the
capture, asserts the activation thread, and completes the handoff. A timeout fails the snapshot
rather than reading Unity state from a worker thread. The pump is required because this game build
invokes `ModBehaviour` activation hooks on an inactive holder without scheduling frame messages, and its
ambient synchronization context does not dispatch posted work.

Software Inc. also stops Unity frame dispatch when it loses foreground focus by default. The
Software Inc.-specific Python client therefore starts the bridge operation, foregrounds the exact
already-running game process, and awaits the response. The mod does not change
`Application.runInBackground`. This choreography does not bypass the game's pause state or grant
gameplay mutation authority.

The compiled mod declares Software Inc.'s documented `GiveMeFreedom` flag solely because its
authenticated loopback listener and owner-only token read require that permission. Installation
therefore requires the explicit `--approve-broad-access` option. It binds only to `127.0.0.1`, owns
no save serialization, invokes no gameplay mutation API, and advertises an empty action catalog.

## Consequences

Company, team, and employee collections can be observed completely for the selected public fields.
Finances are partial because the detailed ledger is not modeled. Work items, products, and offices
initially expose honest collection summaries and stay partial until stable per-entity semantics are
live-proven. No observation result grants action authority.
