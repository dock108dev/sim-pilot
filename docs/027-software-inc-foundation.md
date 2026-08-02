# Software Inc. Reference Foundation

## Status

Prompt 1 implements the game-neutral registration, macOS Steam discovery, and reversible official
code-mod lifecycle probe. Phase 2 adds a separately installed read-only semantic bridge. It does
**not** implement natural-language gameplay compilation, planning, action execution, or
reconciliation. Every gameplay catalog for Software Inc. remains empty.

Software Inc. was frozen as a reference capability on 2026-08-02. This guide preserves the
implemented boundary and historical proof; it is not an active flagship or authorization for
further game-specific roadmap work. See `037-software-inc-freeze-checkpoint.md`.

Rail Route and OpenTTD remain retained integrations and evidence. They are not templates whose
game-specific assumptions should be copied into Software Inc.

## Product boundary

The intended product loop remains:

1. understand a high-level player objective;
2. observe current game state;
3. select one supported action;
4. validate policy, authority, and action preconditions;
5. execute once;
6. observe fresh state and verify the claimed effect;
7. continue, complete, request approval, or report blocked.

Prompt 1 establishes whether the local game and official mod surface are suitable for that loop.
The lifecycle probe cannot inspect employees, teams, projects, products, offices, finances, or any
other gameplay entity, and cannot change the game.

## Discovery contract

`SoftwareIncDiscoveryResult` is a strict schema-versioned report. On macOS it discovers:

- Steam app `362620`, the resolved library and exact application/executable paths;
- Steam build ID, bundle metadata, executable and running architectures, process identity and
  parentage;
- Unity version, Mono versus IL2CPP, managed assembly paths and SHA-256 fingerprints;
- the presence of the official `ModMeta` and `ModBehaviour` API markers;
- official mod root, the game-root `Saves` directory, and conservative legacy save/log path
  candidates;
- Accessibility trust, functional screen capture while running, and the exact front-window title,
  bounds, and display scale when macOS exposes them;
- probe source, ownership, enablement, lifecycle-log evidence, and proven game `Versioning` value;
- typed coverage, warnings, blockers, structural compatibility, and live-proof state.

The `CFBundleShortVersionString` value is reported separately as `bundle_version`; it is not treated
as the gameplay version. `product_version` is populated only from the loaded probe's managed
`Versioning` API. Missing evidence remains unavailable and never receives a guessed value.

The current machine baseline discovered on 2026-07-22 is the macOS Steam build `23094975`, Unity
`2018.4.36f1`, Mono, and x86_64. Assembly hashes are included in `doctor --json` rather than copied
into an allowlist. Structural compatibility is not a promise of gameplay support.

## Commands

Read-only diagnosis is safe while the game is open:

```bash
uv run sim-pilot software-inc doctor
uv run sim-pilot software-inc doctor --json
uv run sim-pilot software-inc capabilities
uv run sim-pilot software-inc probe doctor
```

The official probe file lifecycle requires Software Inc. to be closed:

```bash
uv run sim-pilot software-inc probe install
uv run sim-pilot software-inc probe verify
uv run sim-pilot software-inc probe disable
uv run sim-pilot software-inc probe uninstall
```

`install` writes only:

```text
<Software Inc root>/DLLMods/SimPilotDiscoveryProbe/SimPilotDiscoveryProbe.cs
```

and an owner-only ownership manifest under:

```text
~/Library/Application Support/Sim Pilot/software-inc/probe/install-manifest.json
```

The source file is copied atomically and checksum recorded. Repeated installation is idempotent.
Disable renames only the unchanged owned source. Uninstall refuses a changed owned source and
preserves every unknown file. A later reinstall deletes only the two documented, reproducible
source-compiler cache files in this dedicated probe directory so the game cannot reuse stale code;
any other occupant still blocks installation. None of these operations edits the application
bundle, Steam configuration, saves, preferences, or other mods.

Software Inc. deliberately defaults a newly accepted code mod to inactive. After installation,
launch the game, open **Mods → Code mods**, and toggle `SimPilotDiscoveryProbe` on once. That
player-visible step creates Software Inc.'s own activation setting; Sim Pilot neither writes nor
claims ownership of it. `probe_enabled` means the manifest-owned source file is enabled, while
`probe_loaded` and `live_supported` require a current-process lifecycle marker. Diagnostics tell
the operator when the one-time in-game activation is still pending.

## Exact API validation

The checked-in probe can be compiled against one installed build without modifying it:

```bash
dotnet build software_inc_bridge/probe/SimPilotDiscoveryProbe.csproj \
  -p:SoftwareIncManagedPath="/absolute/path/to/Contents/Resources/Data/Managed" \
  --configuration Release
```

The exact local API requires `ModBehaviour.OnActivate()` and
`ModMeta.ConstructOptionsScreen(RectTransform, bool)`. The build is an offline compatibility test;
Software Inc. loads the manifest-owned source mod through its official code-mod mechanism.

The probe requests no `GiveMeFreedom`, declares no `Serialize` or `Deserialize`, starts no listener,
and stores no gameplay data. It logs schema-versioned `activated`, `game_ready`, and `deactivated`
markers. A loaded marker upgrades discovery from structurally compatible to live-supported for
this discovery milestone only.

## Live validation

On 2026-07-22 the exact local macOS build produced `activated` and `game_ready` markers on managed
thread 1 and reported product version `1.8.41`. The matching Steam build is `23094975`, the Unity
runtime is `2018.4.36f1`, and the scripting backend is Mono. The functional capture path also
confirmed a 2.0 Retina scale. This evidence proves only discovery and official code-mod lifecycle
support; it does not promote any semantic observation or gameplay action.

## Phase 2 gate

The exact lifecycle proof authorized implementation of the Phase 2 bridge described in
`028-software-inc-semantic-bridge.md`. The bridge uses the same protocol core without importing
Rail Route domain assumptions. The first action remains a separate later gate.
