# ADR-019: Rail Route UI Actuation and Semantic Verification

**Status:** Accepted and implemented offline; live route proof pending plugin restart

**Date:** 2026-07-22

## Context

Sim Pilot's product contract is terminal-first natural-language computer control. Phase 2 proved
nine read-only semantic surfaces. The experimental protocol-v2 `set_route` path exposed a narrow
game method but did not prove the reusable player-visible control loop. Its live attempts were
rejected before mutation.

## Decision

Normal mouse and keyboard input is the production Rail Route mutation mechanism. Game Bridge
Protocol v3 and adapter `rail-route-ui-observer-v1` are read-only and advertise an empty gameplay
action catalog. They provide identity and independent postconditions.

UI capabilities are separate. The first catalog contains only `set_route_ui`, restricted to the
paused canonical Test Yard and route `SIG-W-IN -> SIG-C-W`. A synchronized observation brackets a
Retina screenshot with semantic snapshots, verifies bridge/session/map/save continuity, recognizes
four visible manual signals, and maps them by stable semantic grid order. Each click uses a fresh
frame. The origin click must produce a visible preview change before the destination click. The
final route and allocation must appear semantically. An input that cannot be verified is never
retried.

## Consequences

- The installed bridge has no reachable gameplay method.
- Screen pixels are not retained; owner-only JSONL traces store hashes and typed evidence.
- Initial UI targeting is intentionally limited to the canonical Test Yard layout.
- Construction, rename, rotation, cancellation, dispatch, compounds, background play, Windows,
  and native ARM64 remain unavailable.
- The historic v2 models and live rejection findings are evidence, not production authority.
