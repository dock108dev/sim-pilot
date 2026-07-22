# Sim Pilot Test Yard Specification

**Status:** Canonical macOS artifact created; live protocol-v3 UI proof pending

The canonical Sim Pilot Test Yard is a disposable Rail Route `2.3.24` map for proving exactly one
UI action without touching ordinary gameplay. It is stored at
`tests/fixtures/rail_route/test_yard/v1/artifact` with its machine-readable contract in the adjacent
`manifest.json`.

## Phase 3 layout

The action yard intentionally contains the smallest deterministic topology needed by the accepted
Phase 3 boundary:

- one straight connected track;
- four manual signals, left to right: `SIG-C-W`, `SIG-W-IN`, `SIG-C-E`, `SIG-E-IN`;
- no stations, platforms, switches, trains, incoming traffic, schedules, or contracts;
- initial clock `08:00:00`, paused;
- one intended request: `SIG-W-IN -> SIG-C-W`.

An earlier pre-action draft proposed stations, platforms, a switch, and scheduled trains. That
fixture was never created and would introduce unrelated moving state. It was superseded when
ADR-019 narrows Phase 3 to one UI-driven signal-to-signal route allocation. Richer dispatch and conflict
scenarios require a later versioned fixture and capability decision.

## Artifact record

The map was created and named only through Rail Route's supported editor UI. Sim Pilot did not
construct or edit Rail Route save bytes. The canonical map identity is
`52da8212-cb1b-44b6-b067-7e7367d02c6c` on Steam build `22547955`.

The repository contains only the editor export files, not an autosave or ordinary gameplay save:

| File | SHA-256 |
|---|---|
| `level.txt` | `eec885feac543363bdef68bb04eb366a077196df6df263e1d06f09f442e2d536` |
| `savedMap.bytes` | `6839a1bce78cfd0850cf20c5727ca538d8f754d7c713117e509c7c120c54dae4` |

Windows remains unverified.

## Live acceptance

Import or copy the artifact as disposable data, load it in play mode, and pause before the first
snapshot. Protocol v3 and the UI controller must prove:

1. an empty bridge action catalog, UI capability `set_route_ui`, and all four unique signal names;
2. continuous bridge, game-session, map, and available save identities;
3. a fresh pre-action snapshot with a free origin and no existing route;
4. one verified origin click followed by a fresh observation and one destination click;
5. a fresh post-action snapshot exposing `SIG-W-IN -> SIG-C-W` and no unrelated route change.

If execution is ambiguous or verification fails, report the request as potentially executed and do
not retry. Restore a fresh disposable artifact for another run; route cancellation is outside this
milestone.

Prague remains the Phase 2 observation proof only. It is never an accepted mutation target.
