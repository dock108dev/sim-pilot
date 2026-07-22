# Sim Pilot Game Bridge Protocol v2

**Status:** Implemented; offline contract and integration validation complete

**Version:** 2

## Boundary

Game Bridge Protocol v2 is a game-neutral protocol carried as length-prefixed UTF-8 JSON over
loopback TCP. One authenticated Sim Pilot client owns the connection. V2 preserves all v1
observation behavior and adds one explicitly negotiated gameplay request: `set_route`.

The frame is a four-byte unsigned big-endian payload length followed by one JSON object. The maximum
payload is 1,048,576 bytes. Connections and reads are bounded. Zero-length, oversized, malformed,
unauthenticated, non-loopback, schema-invalid, out-of-sequence, or stale-identity traffic fails
closed.

## Envelope

Every message contains exactly these keys:

| Field | Type | Meaning |
|---|---|---|
| `protocol_version` | integer | Exactly `2`. |
| `adapter_version` | string | Exact peer adapter contract. |
| `game_id` | string | Stable game identifier; Rail Route uses `rail-route`. |
| `game_version` | string | Exact observed or expected game version. |
| `platform` | string | Runtime platform. |
| `architecture` | string | Runtime process architecture. |
| `bridge_instance_id` | string | New for each loaded bridge instance. |
| `game_session_id` | string | New when the observed game session changes. |
| `map_identity` | identity object | `observed` with value, or explicit `unavailable`. |
| `save_identity` | identity object | `observed` with value, or explicit `unavailable`. |
| `message_id` | string | Unique delivery identifier. |
| `correlation_id` | string or null | Request identifier for a response. |
| `bridge_sequence` | positive integer | Contiguous sequence in each direction. |
| `message_type` | string | One of the v2 message types. |
| `timestamp` | RFC 3339 UTC datetime | Message creation time. |
| `payload` | object | Exact type selected by `message_type`. |

Unknown or missing keys fail validation. Golden JSON uses sorted keys and compact separators.

## Messages and handshake

V2 implements:

- `client_hello`, `bridge_hello`, and `authentication_failure`;
- `heartbeat` and `capability_manifest`;
- `full_snapshot_request` and `full_snapshot_response`;
- `resynchronization_request` and `protocol_error`;
- `set_route_request` and `set_route_response`.

The selected tuple is exactly protocol `2`, game `rail-route`, game `2.3.24`, and adapter
`rail-route-set-route-v1`. The capability manifest must advertise exactly one gameplay action,
`set_route`; any wider, missing, or unknown catalog is incompatible.

Full snapshots are immutable. They include capture markers, bridge sequence, identities,
game/runtime fields, deterministic entity ordering, explicit per-surface coverage, warnings, and
limitations. Coverage values are `observed_complete`, `observed_partial`, `unsupported`,
`unavailable`, and `failed`. An unobserved surface is never an authoritative empty collection.

## Atomic `set_route`

The client must authenticate, negotiate the exact capability catalog, and obtain a fresh full
snapshot on the same connection immediately before requesting an action. A request contains only:

- canonical origin and destination signal names;
- expected bridge instance and game session IDs;
- the exact sequence of that latest full snapshot.

The bridge accepts the request only if those values still match. It resolves each signal exactly
once, validates play mode, signal type and state, topology uniqueness, path occupancy, allocation
conflicts, and Rail Route's own routability predicate. Only then may the Unity main thread invoke
one typed route-creation method once. There is no retry path and no arbitrary method, reflection,
filesystem, console, cancellation, dispatch, automation, or multi-action request.

The response distinguishes rejection before execution from an executed request whose result could
not be proven. After every response, the client requests a new full snapshot on the same connection.
Success is returned to the terminal only when bridge/game/map/save identity is continuous and the
fresh `signals` and `routes` surfaces expose exactly the requested new allocation without changing
unrelated active routes. Ambiguous or unexpected state fails closed and is never retried.

## Sequencing and recovery

Within one bridge instance, bridge sequences increase by exactly one and message IDs do not repeat.
A duplicate, gap, rollback, unexpected correlation, identity change, or action request that does not
name the latest synchronized snapshot invalidates the operation. Resynchronization can restore
observation state, but it never replays or retries a gameplay request.

A bridge restart changes `bridge_instance_id`; a game/session boundary changes `game_session_id`.
Available map and save identities must also remain equal. Null identity means unavailable, never
inferred continuity.

## Security and versioning

The server binds only to `127.0.0.1`. The random owner-only token is stored outside the game
installation and is never logged or returned. The boundary protects against remote exposure,
unauthenticated local access, malformed input, protocol confusion, stale delivery, and accidental
authority expansion. It does not defend against another process running as the same OS user.

Shared fixtures under `tests/fixtures/game_bridge/v2` are consumed by Python and C# tests. Any wire
shape or authority change requires a new protocol version. V1 remains the historical read-only
record and is intentionally incompatible with the v2 action adapter.

## Validation record

Protocol v1 and adapter `rail-route-readonly-v1` were live-proven on 2026-07-21 against Rail Route
`2.3.24`, Steam build `22547955`, Unity `2021.3.45f2`, and BepInEx `5.4.23.5` on macOS x86_64 under
Rosetta. Prague proved nine observation surfaces, stable identities, reconnect/resynchronization,
loopback authentication, deterministic snapshots, and unchanged save/community-level hashes.

Protocol v2 and adapter `rail-route-set-route-v1` currently pass strict Python golden/client tests,
C# protocol/server integration tests, and an offline plugin build against the pinned game assembly.
The v2 record is not promoted to live-proven until the installed adapter is restarted against the
disposable populated Test Yard and one `SIG-W-IN -> SIG-C-W` allocation is observed in a fresh
post-action snapshot.
