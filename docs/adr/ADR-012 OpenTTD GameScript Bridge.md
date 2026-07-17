# ADR-012: Use a Constrained Bidirectional OpenTTD GameScript Bridge

## Status

Accepted — Constrained Go

## Context

The Task 6 Admin Network adapter provides server, company-economy, aggregate
count, and narrow verified RCON capabilities. Meaningful simulation tasks need
richer structured state and, eventually, company gameplay commands.

OpenTTD 15.3 officially supports both `GSAdmin.Send` to Admin Network packet 124
and Admin Network packet 6 to `GSEventAdminPort`. `GSCompanyMode` selects any
existing company and executes normal commands using that company's authority and
funds. Task 7A proved the channel, company reads, test mode, reversible mutation,
save/load, reconnect, and process restart on an AI-created disposable company.
It did not live-prove construction in a human-created company.

## Decision

Adopt Option B, a bidirectional GameScript bridge, with constrained capability
negotiation. Task 7B may implement production telemetry, protocol v1, recovery,
and only actions demonstrated by live probes. It must not expose infrastructure
or vehicle construction until the human-company construction gate passes.

Admin Network remains the transport and independent source for server lifecycle
and company summaries. GameScript supplies richer state and a typed command
endpoint. Runtime depends on adapter/domain interfaces, never GameScript or wire
internals.

## Consequences

- The bridge is official and does not require UI automation or an OpenTTD fork.
- A bridge GameScript must be installed and selected; only one GameScript can run.
- Existing saves without the bridge are not automatically controllable.
- Sim Pilot must implement correlation, deduplication, strict validation,
  capability discovery, state verification, and restart resynchronization.
- Writes remain loopback-only, explicitly enabled, allowlisted, and scoped to a
  selected company.
- Unsupported actions cannot enter compiler or decision-provider catalogs.

## Rejected alternatives

- One-way telemetry cannot supply a coherent verified action channel.
- NoAI controls its own company, not an existing human company.
- UI input is fragile and excluded.
- A patched OpenTTD fork has unacceptable initial distribution and maintenance
  cost while the official channel remains viable.

## Evidence

See `docs/004-openttd-gamescript-capability.md` and the isolated
`discovery/openttd_gamescript` probes and sanitized results.

## Task 7B implementation note

Protocol v1 implements snapshot-only telemetry and the one live-proven command,
`set_company_name`. Production API validation narrowed one discovery claim: the
GameScript package does not expose a supported human/AI status getter in the
OpenTTD 15.3 API surface used by the package. Admin Network therefore remains
the sole source for that field. This does not broaden or reverse the constrained
go decision. Construction, state deltas, and generalized events remain absent.
