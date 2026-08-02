# Software Inc. Phase 2 Read-Only Semantic Bridge

## Delivered boundary

Phase 2 composes the exact Software Inc. 1.8.41 public API with Game Bridge Protocol v3. It provides
authenticated, main-thread semantic snapshots and deterministic terminal queries. The capability
Phase 2's original manifest contained eight observation surfaces and zero gameplay actions:

- `game_state`, `company`, `finances`, `teams`, and `employees`;
- `work_items`, `products`, and `offices`.

Game state, company, teams, and employees expose selected public values. Finances are partial.
Work items, products, and offices are partial collection summaries; they are not claimed as complete
entity models. Map identity is unavailable because the proven API does not expose one. Save identity
uses `GameSettings.AssociatedSave.UniqueName` only when present.

## Authority and installation

The semantic bridge is independent of the least-authority discovery probe. Software Inc.'s compiled
mod API requires the documented `GiveMeFreedom` opt-in for loopback networking and reading the
authentication token. Sim Pilot does not silently accept that permission:

```bash
uv run sim-pilot software-inc bridge doctor
uv run sim-pilot software-inc bridge install --approve-broad-access
uv run sim-pilot software-inc bridge verify
```

Close Software Inc. before install, disable, or uninstall. Install owns one DLL under
`DLLMods/SimPilotBridge` plus an owner-only manifest and random token under
`~/Library/Application Support/Sim Pilot/software-inc/bridge`. It does not edit saves, the app
bundle, Steam settings, activation settings, or other mods. Enable **Sim Pilot Read-Only Bridge** in
**Mods → Code mods** and accept Software Inc.'s permission warning. The server listens only on
`127.0.0.1:18462` and accepts one authenticated client.

Recovery is checksum gated:

```bash
uv run sim-pilot software-inc bridge disable
uv run sim-pilot software-inc bridge uninstall
```

Unknown files are preserved. Changed owned bytes stop recovery for manual review.

## Terminal observation

With a playable company loaded:

```bash
uv run sim-pilot software-inc bridge capabilities
uv run sim-pilot software-inc bridge observe
uv run sim-pilot software-inc bridge observe --json
uv run sim-pilot software-inc bridge list teams
uv run sim-pilot software-inc bridge list employees
uv run sim-pilot software-inc bridge list work-items
uv run sim-pilot software-inc bridge list products
uv run sim-pilot software-inc bridge show team "Core Team"
uv run sim-pilot software-inc bridge show employee "Jane Doe"
```

Collection names accept hyphens or underscores; `show` also accepts the singular aliases `team`,
`employee`, `work-item`, `product`, and `office`. Entity references match a stable ID or exact
observed string value and fail on ambiguity.

## Read-only proof

Pause the game, use a disposable session, and run:

```bash
uv run sim-pilot software-inc bridge prove-read-only
```

The proof authenticates twice across a reconnect, requires unchanged bridge/session identity and
an empty action catalog, fingerprints semantic state, and hashes every file under all discovered
Software Inc. save roots before and after. Logs and mod activation settings are outside those save
roots. Any semantic drift, identity change, or save-byte change fails the proof.

## Build and current validation status

The bridge builds against the exact installed managed assemblies:

```bash
dotnet build software_inc_bridge/bridge/SimPilotSoftwareIncBridge.csproj \
  -p:SoftwareIncManagedPath="/absolute/path/to/Contents/Resources/Data/Managed" \
  --configuration Release
```

The compiled target is .NET Framework 4.7.2, which produces a classic `mscorlib` assembly for
Software Inc.'s Unity 2018 Mono runtime. `netstandard` artifacts are not installable: the exact
macOS player does not ship `netstandard.dll`.

Offline validation covers the injected game-neutral contract, strict authenticated transport,
Unity main-thread pump handoff, empty action catalog, installer approval and checksum failure
paths, recovery, terminal queries, Ruff, Pyright, pytest, and a warning-free exact C# build.

Software Inc. stops Unity frame dispatch when it loses foreground focus. The Python client begins
each handshake or snapshot request and then foregrounds the already-running exact Software Inc.
process while awaiting the response. It never launches the game. This keeps focus choreography out
of the mod and leaves Unity's `Application.runInBackground` setting unchanged.

## Live proof

Phase 2 was live-proven on macOS against Software Inc. 1.8.41, Steam build 23094975, in a paused
disposable company. The authenticated client observed all eight then-advertised surfaces, and the action
catalog remained empty. Across a fresh authenticated reconnect, the semantic fingerprint remained
`bf1a3105630dd4e152e030250010958c7c32be322cb79cd34d81ea2a059bbace` and the one discovered save
file retained fingerprint `3a295d8cf84d423fec34e850844ff4ee9f0067a098401827be83b950a8c256f1`.

The Python foreground coordinator was proven against the already-running bridge without replacing
the loaded mod: it begins each request, foregrounds the exact existing Software Inc. process, and
awaits the response. The rebuilt and installed bridge DLLs had identical SHA-256
`3b0ae6ce3cff2719083f5ce026a0770803c230aabcc26f3e96d42e239a6a8110`, so no restart was required.
