# Rail Route Terminal Control

## Status

Implemented and live-verified against Rail Route 2.3.24, Steam app `1124180`, build `22547955`, on
macOS at 1920x1080 fullscreen-window resolution.

## Product slice

The player can start Sim Pilot from Terminal and issue plain-English status, pause, and resume
instructions. Sim Pilot performs this bounded cycle:

1. discover the exact game version and running process;
2. activate Rail Route and capture a fresh screen;
3. recognize the selected time control deterministically;
4. validate that the requested transition is meaningful;
5. send the game's Space binding at most once;
6. capture a new screen and verify the intended selected control;
7. report success or a typed failure.

An already-satisfied instruction succeeds without sending input. A menu, loading screen, disabled
tutorial control, ambiguous observation, unsupported version, missing Accessibility permission, or
failed screen capture prevents execution. If input is sent but the new state is not observed, the
command fails without retry.

## Commands

From the repository root:

```shell
uv sync --all-groups
uv run sim-pilot rail-route doctor
uv run sim-pilot rail-route status
uv run sim-pilot rail-route do "pause the game"
uv run sim-pilot rail-route do "resume the game"
uv run sim-pilot rail-route play
```

`doctor` reports the app path, executable, version, Steam build, process, Accessibility state, and
compatibility result. `status --json` and `do ... --json` expose the strict observation and control
result models.

The interactive session supports ordinary variants such as `hold the game`, `continue playing`,
and `what is the game doing?`. Conflicting or unknown instructions fail closed.

## Safety and trust boundary

This screen-control adapter does not modify the Rail Route application, inject a plugin, scrape
process memory, or claim an external API. It uses only macOS process discovery, screen capture,
application activation, and the game's own Space binding. Recognition is limited to the
version-pinned time controls. The separately installed read-only semantic bridge is documented in
[025-rail-route-semantic-bridge.md](025-rail-route-semantic-bridge.md) and does not change this
adapter's behavior or authority.

Rail Route does not expose its Unity controls as semantic macOS Accessibility elements. The current
screen boundary therefore cannot resolve a train, signal, platform, or route identity. Those actions
are not approximated with coordinates.

## Route-setting gate

`route`, `dispatch`, `signal`, `platform`, and `train` instructions return an explicit unsupported
result. Route-setting may be added only after a disposable live probe proves:

1. stable semantic identities for both route endpoints;
2. observation of relevant occupancy and route preconditions;
3. deterministic rejection of ambiguous or impossible routes;
4. one bounded execution mechanism; and
5. an independent postcondition proving the intended route—not merely a click—was established.

The read-only portion of the preferred small, versioned local bridge is now implemented. Gameplay
route-setting remains behind this gate. Screen-coordinate automation remains a discovery fallback,
not production authority.

## Live evidence

The implementation was exercised on 2026-07-21 against the running Story of Jozic Prague map after
leaving the narrated tutorial. The observer measured the normal-speed selection, the controller
sent one Space input, and the next observation identified the pause selection. A second command
observed pause, sent one Space input, and verified normal speed. Both transitions completed without
retry.
