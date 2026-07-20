# Phase 10A: Named OpenTTD Entity Inspection Discovery

## Decision

Production-quality named-entity inspection is **unsupported** on the proven OpenTTD 15.3
integration. Sim Pilot does not add an inspection command to the GameScript protocol, does not use
RCON or UI automation as a substitute, and does not claim that a client moved when no readable
postcondition exists.

`sim-pilot analysis inspect ANALYSIS_ID FINDING_ID` is an explicit fail-closed capability check. It
resolves one vehicle, station, town, or industry from the retained typed finding, performs a fresh
read-only collection, validates world/save/company/capability continuity and current entity
presence, and returns a typed `unsupported` result. Asking a gameplay question never invokes this
command. The result records `executed=false` and `economic_mutation=false`.

## OpenTTD 15.3 source discovery

The review is pinned to the supported OpenTTD 15.3 tag.

- [`ScriptViewport`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_viewport.hpp)
  exposes `ScrollTo`, `ScrollEveryoneTo`, `ScrollCompanyClientsTo`, and `ScrollClientTo`.
  `ScrollTo` requires a non-multiplayer game. The other calls dispatch a deity viewport command.
- [`script_viewport.cpp`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_viewport.cpp)
  confirms that local scrolling directly calls `ScrollMainWindowToTile`, while multiplayer
  scrolling posts `CMD_SCROLL_VIEWPORT`.
- [`viewport.cpp`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/viewport.cpp#L3616-L3645)
  applies that command only on a target client's local company/client match. Its empty command cost
  proves command processing, not that a particular remote viewport reached the tile.
- [`ScriptWindow`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_window.hpp.in)
  can close, query, or highlight an already-open local window only when the game is not multiplayer.
  It provides no method to open a named vehicle, station, town, or industry window.

Neither Admin Network protocol 3 nor GameScript API 15 exposes the current client viewport,
open-window state for multiplayer clients, focus state, or a client acknowledgement readable by the
bridge. Therefore Sim Pilot cannot independently verify the requested effect. A successful command
return would be acknowledgement-only and does not meet ADR-011/ADR-012 verification requirements.

## Live discovery evidence

On 2026-07-20 the configured disposable environment reported:

- OpenTTD `15.3`, Admin protocol `3`, dedicated server `true`;
- bridge protocol/capability version `2`;
- world `spb-1636440848-1049736244`, save generation `439`;
- advertised actions: `set_company_name` only;
- Admin and GameScript write flags both `0`.

The production bridge therefore does not advertise inspection. The dedicated server was launched
with `-D -x`, so it has no local viewport for `ScrollTo`. Adding a multiplayer scroll command would
still leave no independently readable client-side postcondition. No inspection message was sent
during discovery.

The completed CLI verification resolved live vehicle
`vehicle:4edad39be86b8f7f46c33ff7` in the same world and returned
`no_verifiable_inspection_capability`. Its evidence recorded the sole advertised action
`set_company_name`, `executed=false`, and `economic_mutation=false`.

## Typed boundary and safety

The typed request includes the analysis and finding IDs, supported entity kind, canonical entity
ID, retained snapshot identity, target label, and `focus_named_entity` intent. The typed result
includes the action, `unsupported` status, reason, `executed`, `economic_mutation`, and structured
verification evidence.

Resolution fails before any capability assessment when the finding is missing, ambiguous, names an
unsupported kind, or the retained entity is absent. Live assessment rejects a changed world,
save generation, company, bridge company context, capability fingerprint, or entity disappearance.
Duplicate explicit invocations produce the same deterministic action ID and never send a bridge
command.

## Reconsideration gate

Production inspection can be reconsidered only after a disposable live probe demonstrates all of:

1. an exact, allowlisted OpenTTD 15.3 mechanism for the intended entity kinds;
2. a separately scoped inspection capability and opt-in if the mechanism changes client UI state;
3. target-client selection without ambiguity;
4. an independently readable postcondition proving the correct entity was opened or focused; and
5. reconnect, restart, stale-reference, and duplicate-delivery behavior that remains fail closed.

Until then, economic gameplay automation and client UI control remain on hold.
