# OpenTTD World Observation

**Status:** Implemented

**Version:** 1.0

Phase 8A expands the OpenTTD adapter from a company health summary into a versioned, immutable
world snapshot. This is an observation feature only: it does not add construction, vehicle,
order, routing, scheduling, or optimization actions.

## Data flow and versioning

```text
OpenTTD 15.3 -> SimPilotBridge protocol v2 -> strict bridge entities
             -> OpenTTD adapter -> canonical WorldSnapshot schema v1
             -> existing Observation.state
```

The GameScript wire models stay inside `sim_pilot.openttd.gamescript`. The adapter translates them
into game-neutral domain models and publishes the resulting `WorldSnapshot` in the unchanged
`OpenTTDObservationState.world` field. Every canonical model is strict, frozen, rejects unknown
fields, and carries `schema_version=1`. Raw GameScript IDs are replaced with deterministic opaque
IDs scoped to the saved script instance; they are stable across observations and reloads of that
world but are intentionally different in another world.

Protocol v1 remains parseable for bridge compatibility. A rich world snapshot requires protocol
v2 and the `openttd-gamescript-v2` adapter contract.

## Canonical model

`WorldSnapshot` contains metadata, coverage, companies, towns, industries, selected-company
stations and vehicles, inferred routes, cargo flows, and precomputed typed changes. Metadata
records the world and snapshot identities, OpenTTD version and date, capture start/completion game
dates, completeness, capability fingerprint, save generation, bridge sequence, and UTC capture
time. `observer_company_id` identifies the selected company using the same canonical opaque-ID
scheme, so downstream analysis never needs a raw GameScript company slot.

The entity models expose:

- `Company`: economy, typed fleet counts, station count, headquarters, AI status when known, and
  performance.
- `Town`: population, coordinates, selected-company rating, growth, cargo flows, and derived
  service relationships.
- `Industry`: type, coordinates, cargo production/acceptance, ownership when applicable, and
  derived nearby selected-company stations.
- `Station`: owner, location, facilities, cargo acceptance/waiting, and derived town, industry,
  and vehicle relationships.
- `Vehicle`: type, engine subtype, age, current and prior profit, running state, optional location,
  current order, complete observed order cycle, depot status, owner, and inferred route.
- `Route`: owner, vehicles sharing one normalized order cycle and transport type, ordered stations,
  and Manhattan distance. Route cargo remains empty because protocol v2 does not expose vehicle
  cargo assignment.
- `CargoFlow`: canonical cargo identity plus available quantity, waiting, production, acceptance,
  transported amount/percentage, scope, and period.

Optional fields mean the source did not provide a defensible value. The adapter does not use zero
or an empty string as a substitute for unavailable data.

## Capability matrix

| Category | Phase 8A status | Source and boundary |
|---|---|---|
| Server metadata | Available | Admin Network connection metadata |
| Map metadata and game date | Available summary | Admin map dimensions/seed/date; no complete map scan |
| Companies | Partial | All companies from GameScript; selected-company AI status and current economy overlaid from Admin |
| Towns | Partial | Identity, location, population, growth, selected-company rating; acceptance/production remains scoped cargo data |
| Industries | Partial | Identity, type, location, cargo production/acceptance; nearby stations are adapter-derived |
| Stations | Partial | Selected-company stations, facilities, cargo and relationships; other-company stations are not scanned |
| Vehicles and orders | Partial | Selected-company fleet and order cycles; status is a bounded bridge projection |
| Routes | Derived | Normalized vehicle order cycles, not OpenTTD pathfinder routes |
| Cargo | Partial | Cargo definitions and positive scoped flow observations; zero-value absence is not a complete economy history |
| Tiles and infrastructure | Unavailable | No per-tile or network-topology collection in protocol v2 |
| Terrain | Unavailable | GameScript can query it, but protocol v2 does not expose it |
| Economy | Partial | Company quarterly values and scoped cargo flows, not all price/settings/history data |
| Native events | Unavailable | Snapshot comparison supplies canonical changes; GameScript event streaming is not implemented |

Coverage is embedded in every snapshot as typed `CapabilityCoverage` records so consumers do not
need to infer absence from empty collections.

## Bridge snapshot generation

After the existing summary snapshot, the GameScript sends a manifest, bounded collection pages,
and a completion record. Collections are companies, towns, industries, stations, vehicles, orders,
and cargo. One item per page keeps each outbound JSON object below OpenTTD's 1,450-byte limit. The
script yields after every eight messages so large saves do not monopolize the cooperative script
loop.

The client validates manifest counts, collection names, item types, page indices, page counts,
duplicates, total items, snapshot identity, and completion before publishing anything. A missing
or inconsistent page fails the capture; partial transport data is never labeled complete. Capture
start and end dates make the non-atomic scan window explicit.

## Route inference

Routes are an adapter abstraction, not a claim about the exact path vehicles will take. For each
vehicle, the adapter extracts station/depot/waypoint order destinations, preserves order, and
normalizes a cyclic order list to its lexicographically smallest rotation. Vehicles with the same
owner, transport type, and normalized cycle share a route. The stable route ID hashes the
world-scoped owner, transport type, and normalized cycle; it does not depend on vehicle IDs.
Estimated distance is the Manhattan distance between consecutive known station coordinates,
including the closing leg, and requires at least two resolved stations. `inferred_route_type` is
the shared vehicle transport type (`rail`, `road`, `water`, or `air`).

Conditional behavior, non-stop flags, full-load semantics, wayfinding, track/road connectivity,
and actual traveled distance are not modeled. These limits are why routes remain explicitly
inferred.

## Diff generation

The adapter compares each accepted snapshot with the immediately preceding snapshot from the same
world and stores the result in `changes`; `changes_from_snapshot_id` identifies the baseline. Typed
changes are `entity_added`, `entity_removed`, `field_changed`, and `coverage_changed`. Entity and
field traversal is sorted, making output deterministic.

Removals are emitted only when both snapshots are complete and the relevant collection is not
unavailable. This prevents a failed or narrowed capture from being mistaken for mass deletion.
Diffs are produced during observation, so later consumers can answer what changed without loading
and recomputing an older world. The snapshot history itself is retained only when the enclosing
observation is persisted by the existing runtime; Phase 8A adds no database tables or migrations.

## CLI

Bridge composition must be enabled and an exact v2 bridge must be running:

```bash
export SIM_PILOT_OPENTTD_GS_ENABLED=1

uv run sim-pilot openttd world
uv run sim-pilot openttd towns
uv run sim-pilot openttd industries
uv run sim-pilot openttd stations
uv run sim-pilot openttd vehicles
uv run sim-pilot openttd company
uv run sim-pilot openttd routes
uv run sim-pilot openttd diff --wait-seconds 1
```

Commands print concise tables. Add `--json` to any command for complete canonical JSON. `diff`
keeps one adapter session open, captures twice, and prints the second snapshot's precomputed
changes.

## Performance and limits

World capture work is proportional to observed companies, towns, industries, selected-company
stations, vehicles, orders, cargo types, and positive scoped cargo records. It does not scan every
map tile. The bridge scans once per requested synchronization and the adapter reuses the assembled
snapshot while translating one observation; it does not independently rescan collections.

Practical size and latency depend on save population and GameScript tick rate. Operators should
measure representative large saves using the JSON CLI output and bridge health timestamps. The
strict 1,450-byte outbound packet ceiling, cooperative yielding, non-atomic capture interval, and
selected-company station/vehicle scope are fixed protocol-v2 limitations.

The live Phase 8A acceptance save measured 1 company, 22 towns, 78 industries, 197 stations, 419
vehicles, 100 inferred routes, and 284 cargo-flow records. One capture took 6.67 seconds and three
game days. Canonical translation took 64.84 ms with a 4.10 MB traced peak; strict JSON validation
took 13.64 ms with an 8.37 MB traced peak. The canonical JSON snapshot was 707,156 bytes. These are
single-machine measurements from a busy evolving save, not a universal performance guarantee.

Phase 8B should consume only canonical models and coverage records. It should begin with read-only,
explainable analysis such as unserved-industry candidates, high station waiting cargo, unprofitable
vehicles, route duplication, and changes of interest; it should not add action planning until those
signals are validated against live saves.

Phase 8B now consumes this model through the separate query boundary in
[014-gameplay-analysis-engine.md](014-gameplay-analysis-engine.md). It says “high waiting cargo” or
“potentially underserved,” not “congested,” because tile movement is unavailable. Analyses are not
persisted and comparisons remain explicit and fail closed.
