# ADR-011: OpenTTD Admin Network Observation and Narrow RCON Action

- Status: Accepted
- Date: 2026-07-16

## Context

Sim Pilot needs a supported external observation boundary for a real OpenTTD game. Task 6B must
observe company state without changing the game, patching OpenTTD, parsing process memory, or
claiming that an observation checkpoint can restore authoritative game state. The selected
interface must also preserve the dependency direction `Runtime -> Domain <- Adapter -> Client`.

The decision is pinned to OpenTTD 15.3, commit/tag `14ec60f248547d4d062a1160f0fc26d742319888`,
whose Admin Network version is 3. OpenTTD 15.3 is the stable release evaluated for this milestone;
OpenTTD 16 beta interfaces are not included.

## Decision

Use the official TCP Admin Network protocol as the Task 6B read-only interface. The client joins a
locally bound dedicated server, verifies protocol version 3 and application version 15.3, and polls
date, company information, company economy, and company statistics packets for one configured
company. Task 6B advertises no actions. Task 6C adds only `set_server_name`, gated by
`SIM_PILOT_OPENTTD_ALLOW_WRITES=1`. It uses the documented Admin RCON packet and independently
verifies the postcondition by reconnecting and reading a new welcome packet. RCON completion text
is acknowledgement, not verification.

OpenTTD 15.3 disables the legacy plaintext admin join by default. This prototype requires
`allow_insecure_admin_login = true` only for a loopback-bound development server and refuses to
resolve a configured host to any non-loopback address. A non-empty admin password is still
required. Secure Admin Network authentication is a future hardening item; this restriction must not
be relaxed to reach a remote or multiplayer server.

No GameScript, AI, plugin, patch, NewGRF, or other mod is required. The connection is established at
adapter initialization, remains open across observations, and sends an admin quit before closing.
OpenTTD keeps admin clients connected across a new game or save load, although Task 6B does not yet
reconcile those notifications.

The observable contract contains:

- server name, OpenTTD version, protocol version, dedicated flag, and connected state
- map generation seed, landscape, starting date, width, and height
- raw and formatted calendar date
- company identity, manager, colour, inauguration year, AI status, and bankruptcy quarters
- cash, loan, current-year net income, quarterly company value/performance/cargo
- vehicle counts and station-facility counts by protocol category

The Admin Network does not expose paused state, game speed, gross income, expenses, distinct profit,
depots, active/stopped/lost vehicle states, vehicle profitability, orders/routes, towns, industries,
subsidies, news alerts, or a save identifier. These fields are omitted or explicitly null in the
resource projection. `Observation.tick` is the raw calendar date; it is non-decreasing but can
repeat during the same game day.

## Rejected alternatives

- GameScript exposes richer deity/company state and Admin Port JSON messages, but requires an
  installed Squirrel script embedded in the save and a separately versioned bridge contract.
- The AI API can execute company actions but owns an AI company and is not an external observer of
  an arbitrary human company.
- Console and remote console are command surfaces with unstructured output, not a complete state
  interface. Admin rcon remains a candidate for a very small future server-action set.
- Save parsing is offline, stale, and coupled to an evolving binary save format.
- Debug output, logs, and command logging are incomplete; OpenTTD explicitly describes command
  names and encoded command payloads as unstable and logging-only.
- A plugin or patched build adds distribution and maintenance cost. Process memory access and
  screen observation are brittle, platform-specific, invasive, or explicitly out of scope.

## Licensing and distribution

OpenTTD is GPL-2.0. Sim Pilot does not bundle, modify, or redistribute OpenTTD and does not copy an
OpenTTD executable, save, base set, GameScript, or patch. The independently implemented network
codec follows the public packet field contract. Users install OpenTTD separately from the official
distribution. Any future bundled GameScript or linked OpenTTD-derived component requires a new
licensing review.

## Consequences

Task 6B gets low-latency structured observations and protocol-level errors without contaminating
runtime or persistence code. It cannot observe every candidate resource and cannot restore a game.
Persisted records are observational evidence only. Resume reconnects and compares fresh state with
the last record. Pause, resume, speed, loans, and gameplay actions remain rejected because this
integration cannot both issue them with the required authority and independently observe their
postconditions. Interrupted server-name writes reconcile from prior/requested/current welcome
metadata; ambiguous values never trigger automatic retry.
