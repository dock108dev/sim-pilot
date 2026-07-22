# Rail Route Semantic Bridge

## Implemented boundary

The Rail Route adapter implements Sim Pilot Game Bridge Protocol v3 as a BepInEx plugin and a
game-neutral Python client. It is pinned to Rail Route `2.3.24`, Steam build `22547955`, Unity
`2021.3.45f2`, the observed Mono assembly hash, BepInEx `5.4.23.5`, and adapter
`rail-route-ui-observer-v1`.

This is additive to the existing screen-control slice:

- `rail-route status`, `do`, and `play` still use fresh screen observation and the Space binding;
- `rail-route bridge ...` installs, diagnoses, or reads the semantic bridge;
- the bridge advertises no gameplay actions;
- it cannot cancel routes, dispatch trains, change time, automate play, accept multi-action
  objectives, or call an arbitrary game method.

## Loader decision and platform status

The pinned macOS asset is `BepInEx_macos_universal_5.4.23.5.zip`, SHA-256
`01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323`. Its Doorstop library contains
ARM64 and x86_64 slices. The exact local Rail Route executable and Unity/Mono libraries are also
universal, but the current Steam launch was observed as x86_64 under Rosetta. Therefore:

- x86_64/Rosetta is the first required live validation path;
- native ARM64 is implemented by the upstream loader but remains unclaimed until separately run;
- Windows x64 uses the same C# source and a pinned BepInEx Windows build design, but no Windows
  runtime result is claimed.

The installer never edits `RailRoute.dll`, the application bundle, Steam configuration, or code
signatures. It verifies exact paths, versions, hashes, architecture, archive contents, collisions,
and symlinks; writes an owner-only ownership manifest; and removes only unchanged owned files.
Generated or unknown BepInEx files are preserved for explicit review. Steam updates invalidate
compatibility and never trigger automatic reinstallation.

## Identity and capability rules

`bridge_instance_id` is random for each plugin load. `game_session_id` is derived only from
the current live session boundary and must change on a game/session restart. Map and save identities
are emitted only when a stable source is demonstrated; otherwise their envelope values are null and
their coverage is `unavailable`.

The v3 capability manifest has an empty gameplay-action catalog. UI actions are negotiated outside
the bridge and use snapshots only for identity, preconditions, and postconditions. Any wider bridge
authority requires another explicit protocol and capability decision.

## Field evidence and coverage

Offline assembly inspection found direct public managed APIs for Rail Route time and repository
state. The bridge uses compile-time types only; it does not walk private object graphs or expose raw
objects. Public candidates still require live comparison before being promoted from unavailable or
unsupported coverage.

| Surface | Candidate source | Current contract |
|---|---|---|
| Application/game version | Unity `Application.version` | Exact runtime identity. |
| Unity version | Unity `Application.unityVersion` | Exact runtime identity. |
| Process platform/architecture | runtime APIs | Exact runtime identity. |
| Current time | `Game.Time.TimeController.CurrentTime` | Live-observed; matched the visible paused clock at `08:08:09`. |
| Pause/speed | `Game.Time.TimeController` public properties | Live-proven paused at `08:08:09.0200000` with normalized speed `paused`. |
| Interaction mode/load state | public controller context | Live-proven as `play` on Prague. |
| Map/save | level definition UUID and loaded-save public fields | Live-proven for map `prague` and its autosave; stable across reconnect and repeated snapshots. |
| Trains | typed train repository and train properties | Live-proven with 3 trains; Com1010 resolved by reporting number to a stable UUID, 40 km/h, next station Bubny, and scheduled times. |
| Stations/platforms | typed station and node repositories | Live-proven complete with 22 stations and 74 platforms; Dejvice resolved by exact name and stable reference. |
| Signals/switches/routes | typed node repository | Signals and switches live-proven complete with 182 and 2 entities. `routes` means active `Semaphore.CurrentRouteTo` allocations only; an empty collection does not imply that the rendered diagram has no train occupancy. |
| Track occupancy | public node allocation state plus each on-board train's occupied and lookahead segments | Live-proven with 6 Prague entities. The red diagram segment reported `Occupied`, the green segment reported `Allocated`, and Com1010's UUID identified its occupied segment. Segment identities include train, kind, ordinal, and stable node name. |
| Incoming traffic | public timetable plus train spawn controller | Live-proven against the Upcoming Trains panel: Com1011 at `09:01` and Com1012 at `10:01`, both requesting Dejvice platform 2. Deduplicated by stable UUID; `source` distinguishes `timetable`, `waiting`, and `waiting_to_spawn`. |

Snapshots sort all collections by stable public identity. A failed collection cannot become an
empty authoritative result. Capture start/end markers state whether collection spans Unity frames.

## Commands

```shell
uv run sim-pilot rail-route bridge doctor
uv run sim-pilot rail-route bridge install
uv run sim-pilot rail-route bridge verify
uv run sim-pilot rail-route bridge disable
uv run sim-pilot rail-route bridge uninstall
uv run sim-pilot rail-route bridge capabilities
uv run sim-pilot rail-route bridge observe
uv run sim-pilot rail-route bridge observe --json
uv run sim-pilot rail-route bridge list trains
uv run sim-pilot rail-route bridge list stations
uv run sim-pilot rail-route bridge list incoming-traffic
uv run sim-pilot rail-route bridge list track-occupancy
uv run sim-pilot rail-route bridge show trains <UUID-or-reporting-number>
uv run sim-pilot rail-route bridge show incoming-traffic <UUID-or-reporting-number>
uv run sim-pilot rail-route bridge prove-read-only
uv run sim-pilot rail-route do "set a route from SIG-W-IN to SIG-C-W"
```

The route command requires the disposable canonical Test Yard (or another disposable scenario with
the exact named signals). Sim Pilot performs one preflight, sends one request, and verifies one fresh
post-action snapshot. It never retries an executed request.

For signals, the canonical terminal-facing name is Rail Route's public `Node.FriendlyName` when it
is populated. The generated grid identity in `Node.Name` remains available as the observed
`internal_name` for diagnostics.

Installation is never implicit. Direct launch was live-tested and Rail Route exited through its
Steam restart guard, so the supported BepInEx path must be invoked by Steam. After `doctor` passes
and the game is closed, temporarily set this Rail Route Steam launch option, replacing
`<REPOSITORY>` with the absolute checkout:

```shell
"<REPOSITORY>/rail_route_bridge/scripts/launch-macos-x86_64.sh" %command%
```

Then start Rail Route normally from Steam. The wrapper preserves the observed Rosetta architecture,
rechecks the exact game and Doorstop hashes, and rejects direct invocation or an unexpected Steam
command. Launching the app from the Dock, Finder, or Spotlight bypasses Steam launch options and is
not a supported bridge path; the live run proved that such a launch selected ARM64 and stalled when
the game's x86_64-only Steamworks plugin could not load. The installer does not edit Steam
configuration. Remove the temporary option before
disable/uninstall recovery verification. This path deliberately does not claim native ARM64; a
later native launch must use its own live record rather than replacing the Rosetta evidence.

## Validation status

The default Python and C# suites use fake transports and golden fixtures; they do not require Rail
Route, Steam, a display, BepInEx, or a hosted model. Live tests require
`SIM_PILOT_LIVE_RAIL_ROUTE_BRIDGE=1` and a disposable scenario. The Prague record below is
historical v1 observation evidence; it does not prove UI actuation.

The initial 2026-07-21 macOS gate passed on an x86_64/Rosetta process parented by Steam. Authentication,
loopback restriction, capabilities, full snapshots, reconnect, resynchronization, heartbeat,
stale-identity rejection, identity continuity, restart invalidation, and non-mutation were exercised
live. `game_state.current_time` is `observed_partial`; `paused`, `simulation_speed`, `game_mode`, map
identity, save identity, and every entity surface remain unavailable or unsupported. The gameplay
action catalog remains empty.

The initial Phase 2 artifact passed its populated live gate on 2026-07-21 against paused Prague. The bridge
advertised eight observation surfaces and no gameplay actions. It returned complete coverage
for 22 stations, 74 platforms, 182 signals, 2 switches, and 3 trains; incoming traffic and active
routes were complete empty collections at that instant. The opt-in live suite passed reconnect,
identity continuity, deterministic entity ordering, and stable entity identities. Terminal
`list`/`show` queries resolved Dejvice and Com1010 from public names.

The subsequent read-model refinement passed its populated live gate on paused Prague. It adds a
ninth surface, `track_occupancy`, and expands `incoming_traffic` from the spawn queues to the public
timetable plus spawn state. The bridge returned two timetable entities matching the visible
Com1011/Com1012 panel times and platform, plus six track entities matching the visible allocated and
occupied diagram state. The opt-in live test passed exact-value, coverage, reconnect, and stable-ID
assertions.

The automated read-only proof captured two authenticated snapshots across reconnect while paused.
Their semantic SHA-256 was identical, and the combined SHA-256 of all 14 files under Rail Route's
save and community-level directories was unchanged. The proof used bridge instance
`94a2dd1f-4bd8-48f7-bba7-09bc77907d04` and Prague game session
`0629db81-08c7-4ab6-a676-7473f4a58027`. A failed collection reports `failed` coverage for only
that surface and never becomes an authoritative empty collection.

The refined automated proof used bridge instance
`6a7c3af6-2221-461f-9150-05cfffafee2a` and game session
`cebada3d-9b4f-4047-ae9b-b7cd9306c43a`. Its two semantic fingerprints were both
`b86da5cf818931c47f19996e1a4e6970a6e81cdc92de8fbef8f95efc39e83e0a`; its two combined
14-file save/community fingerprints were both
`2e69f6438949f6b398961a6fb96e3fcc9c8152e14afb03c727cc7cb10f32bc0b`.

Recovery also passed: the plugin was disabled, all 23 unchanged manifest-owned files were
uninstalled, generated BepInEx logs/config/cache were preserved, and Rail Route returned to its
ordinary Steam launch with no listener on port `18461`. Actual save-file hashes were unchanged.
Rail Route's unrelated analytics queue changed during ordinary startup and is not represented as
save immutability evidence.

That uninstalled state was the accepted end of the original recovery test, not the current machine
state. The bridge was subsequently reinstalled and is answering on the pinned Steam/Rosetta launch
path. While Rail Route remains open, `bridge doctor` correctly reports the installation as enabled
and refuses to change bridge files. The built v3 plugin is therefore not considered deployed until
the game is closed, the checksum-gated installer replaces the owned plugin artifact, and Rail Route
is restarted.

Windows x64 currently has a pinned loader asset and build-compatible source design only. A Windows
installer, token ACL verification, launch path, and live validation remain intentionally unclaimed.
