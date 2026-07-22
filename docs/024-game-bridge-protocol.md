# Sim Pilot Game Bridge Protocol v3

**Status:** Implemented offline; live deployment pending a safe Rail Route restart

**Version:** 3

## Boundary

Game Bridge Protocol v3 is a game-neutral read-only protocol carried as length-prefixed UTF-8 JSON
over loopback TCP. One authenticated client owns the connection. The production adapter is
`rail-route-ui-observer-v1`; its gameplay-action catalog is exactly empty. Player-visible mutation
belongs to the separate computer-control boundary in ADR-019.

The frame is a four-byte unsigned big-endian payload length followed by one JSON object. Maximum
payload size is 1,048,576 bytes. Zero-length, oversized, malformed, unauthenticated, non-loopback,
schema-invalid, out-of-sequence, or stale-identity traffic fails closed.

## Envelope and messages

Every message contains strict protocol, adapter, game, platform, bridge/session/map/save identity,
message/correlation identity, contiguous sequence, UTC timestamp, message type, and payload fields.
Unknown or missing keys fail validation.

V3 accepts only:

- `client_hello`, `bridge_hello`, and `authentication_failure`;
- `heartbeat` and `capability_manifest`;
- `full_snapshot_request` and `full_snapshot_response`;
- `resynchronization_request` and `protocol_error`.

There is no gameplay request or arbitrary method envelope. Historic v2 `set_route_request` and
`set_route_response` messages are unknown in v3 and cannot reach the production plugin.

The selected tuple is exactly protocol `3`, game `rail-route`, game `2.3.24`, and adapter
`rail-route-ui-observer-v1`. The manifest advertises nine observation surfaces, full snapshots,
resynchronization, no deltas, and no gameplay actions.

## Observation semantics

Snapshots are immutable and deterministically ordered. They include capture markers, identities,
game state, entity surfaces, warnings, and explicit coverage. Coverage is one of
`observed_complete`, `observed_partial`, `unsupported`, `unavailable`, or `failed`. A failed or
unavailable surface is never an authoritative empty collection.

Within a bridge instance, sequences increase by one and message IDs do not repeat. Duplicate,
gapped, rolled-back, unexpectedly correlated, or stale-identity delivery fails closed.
Resynchronization can restore observation only. Restart changes `bridge_instance_id`; a loaded-game
boundary changes `game_session_id`.

## Security and versioning

The server binds only to `127.0.0.1`. Its random token is owner-only, outside the game installation,
and never logged or returned. The boundary protects against remote exposure, unauthenticated local
access, malformed input, protocol confusion, stale delivery, and accidental authority expansion.
It does not defend against another process running as the same OS user.

V1 is the historic read-only contract. V2 is retained only as experimental direct-action evidence.
V3 supersedes both for the installed UI-observer adapter. Any future wire or authority expansion
requires a new protocol decision.

## Validation record

V1 live-proved the nine Rail Route observation surfaces on Prague, including deterministic
identities, reconnect/resynchronization, authentication, and unchanged save/community bytes.

V3 passes strict Python model/client tests, a read-only C# server suite, formatting/type checks, and
an offline plugin build against the pinned BepInEx and Rail Route assemblies. The current running
process still hosts the older v2 plugin until Rail Route is safely closed, the checksum-owned plugin
is upgraded, and the game restarts through Steam. Live v3 and `set_route_ui` results must be appended
here only after that gate passes.
