# OpenTTD GameScript Bridge Protocol v1

**Status:** Implemented
**Version:** 1.0

## Scope and compatibility

The production bridge is a constrained bidirectional integration for OpenTTD
15.3, Admin Network protocol 3, GameScript API 15, script package version 1,
and Sim Pilot adapter `openttd-gamescript-v1`. It uses the existing authenticated
Admin TCP connection: one `OpenTTDAdminClient` owns authentication, packet
polling, RCON responses, GameScript packet routing, reconnect, and shutdown.

Protocol v1 is strict. Unknown fields, message types, payload variants, or
protocol versions are rejected. There is no minor-version compatibility within
v1; a schema change requires a new negotiated protocol version. GameScript to
Admin JSON is limited to 1,450 UTF-8 bytes and Admin to GameScript JSON to 8,999
bytes. Serialization uses sorted keys and compact separators.

## Envelope and messages

Every message has this envelope:

```json
{
  "protocol_version": 1,
  "sequence": 1,
  "message_id": "stable-message-id",
  "correlation_id": null,
  "script_instance_id": "saved-game-instance-id",
  "message_type": "state_snapshot",
  "game_date": 712223,
  "company_id": 0,
  "payload": {}
}
```

The implemented message set is `hello`, `capabilities`, `heartbeat`,
`state_snapshot`, `command_request`, `command_accepted`, `command_rejected`,
`command_completed`, `command_failed`, `resync_request`, `resync_response`,
`save`, `load`, and `error`. Save/load payloads are defined for compatibility;
the script communicates actual load continuity in `hello` because OpenTTD save
callbacks must not perform communication. State deltas, generic events, and
`command_started` are intentionally absent because Task 7A did not verify them.

Sequences are monotonic during one live script timeline. TCP preserves delivery
order. Duplicate message IDs and gaps outside synchronization fail safely. A
save/load can legitimately roll sequence back to the saved boundary, so a
correlated full resynchronization establishes a new delivery-deduplication
window. The saved command ledger, not delivery sequence, prevents re-execution.

## Handshake and state machine

Sim Pilot subscribes to Admin update type 9 at automatic frequency, sends a
correlated `resync_request`, and requires `hello`, `capabilities`, the matching
`resync_response`, and a full snapshot before becoming synchronized.

```text
disconnected -> connecting -> awaiting hello -> awaiting capabilities
             -> awaiting snapshot -> synchronized
             -> resynchronizing -> synchronized
             -> incompatible | failed
```

The health record contains connection/authentication status, OpenTTD and bridge
versions, saved script instance ID, sequence, heartbeat/snapshot timestamps,
company context, capability fingerprint, current snapshot, state, and degraded
reason. A task resume supplies its persisted health and rejects a different
script instance as a new-game boundary.

## Snapshot and source authority

The full snapshot contains pause state, map dimensions, town count, industry
count, selected company ID/name, cash, loan, aggregate vehicle/station counts,
snapshot ID, and save generation. It is observational and cannot restore or
roll OpenTTD back.

Admin Network remains authoritative for connection, map identity, game date,
company identity/economy, and aggregate counts. GameScript is authoritative for
the added pause/town/industry fields. Shared-field disagreements are retained in
`source_attribution.inconsistencies`; values are not silently blended. The
production API 15 surface does not expose a supported human/AI status getter to
this GameScript, so that field comes only from Admin Network.

## Capabilities and command

The running script publishes the live capability set and a deterministic SHA-256
fingerprint. Protocol v1 supports full snapshots, save/load continuity,
reconciliation, and only one action: `set_company_name`. Deltas, construction,
vehicle management, general console commands, and arbitrary GameScript actions
are not advertised.

`set_company_name` requires a separately enabled local write flag, the expected
capability fingerprint and company context, a prior snapshot ID, a stable
command ID, and a deterministic action fingerprint. The script validates the
company and parameters, runs OpenTTD test mode with accounting, emits accepted
then completed/failed, and produces a fresh snapshot. Sim Pilot accepts success
only after the fresh snapshot and combined observation independently show the
requested name. Cost is zero.

The saved ledger retains the 64 most recent terminal commands. A repeated ID
with the same fingerprint replays its terminal result with `duplicate=true`; a
different fingerprint is rejected. Evicted or lost entries cannot prove an old
outcome, so Sim Pilot must report recovery required and never retry blindly.
Exactly-once execution is not claimed.

## Identity, save/load, and recovery

The script generates an instance ID for a new game and stores it with protocol
state, sequence, generation counters, selected company, last snapshot ID, and
the bounded command ledger. Loading the save restores that identity and
increments the save generation. Restarting Sim Pilot or Admin Network performs a
full resync. Restarting OpenTTD from the same save restores the same identity.
A new game or missing/incompatible saved script state creates a different
identity and blocks automatic task resume.

Copying a save also copies its identity. Two simultaneously operated copies are
therefore not distinguishable by instance ID alone; do not point one task at
both copies. Script absence, heartbeat loss, incompatibility, sequence failure,
and ambiguous command state disable writes and surface health/recovery evidence.

Bridge metadata is stored inside the existing observational
`SimulationCheckpoint.state`; no database migration is required. Persistence
does not connect or synchronize the bridge.

## Installation and operation

Install the package into the OpenTTD profile and select it for a disposable game:

```bash
mkdir -p "$HOME/Documents/OpenTTD/game/SimPilotBridge"
cp openttd_gamescript/sim_pilot_bridge/{info.nut,main.nut} \
  "$HOME/Documents/OpenTTD/game/SimPilotBridge/"
```

Add `SimPilotBridge =` under `[game_scripts]` in `openttd.cfg`, retain the
loopback Admin configuration from `docs/003-openttd-integration.md`, then start a
new disposable game or load a bridge-enabled save. Configure Sim Pilot:

```bash
source "$HOME/Documents/OpenTTD/sim-pilot.env"
export SIM_PILOT_OPENTTD_COMPANY_ID=0
export SIM_PILOT_OPENTTD_GS_ENABLED=1

uv run sim-pilot openttd bridge doctor
uv run sim-pilot openttd bridge capabilities
uv run sim-pilot openttd bridge sync
uv run sim-pilot openttd bridge observe
uv run sim-pilot openttd bridge watch --count 3
```

On a disposable server only, enable and exercise the verified write:

```bash
export SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1
uv run sim-pilot openttd bridge action set-company-name "Sim Pilot Test"
```

Live tests are independently gated:

```bash
SIM_PILOT_LIVE_OPENTTD_GS=1 uv run pytest \
  tests/openttd/test_live_gamescript.py -m live -s
```

The write test additionally requires `SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1` and
restores the original company name. All bridge-only commands remain local and do
not initialize a hosted compiler or decision provider.

## Troubleshooting and limits

- No bridge packets: confirm the game selected `SimPilotBridge`, Admin update
  type 9 supports automatic frequency, and only one GameScript is configured.
- Identity mismatch: the task checkpoint belongs to another new game; do not
  override it. Start a new task or use the existing manual recovery boundary.
- Sequence gap or timeout: reconnect and request a full snapshot; never apply a
  guessed delta or retry an unresolved command.
- Writes disabled: set the GameScript write flag only for a loopback disposable
  server. The Admin RCON write flag is separate.
- Capability mismatch: install the exact OpenTTD 15.3/API 15 package. Unknown
  versions fail closed.

There is no state delta, map/entity paging, event stream, construction, route
planning, fleet optimization, rollback, public multiplayer automation, UI
control, patched OpenTTD build, or generalized multi-game protocol in v1.
