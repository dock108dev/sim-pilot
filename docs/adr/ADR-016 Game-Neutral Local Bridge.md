# ADR-016: Game-Neutral Local Bridge Protocol

## Status

Accepted — read-only v1

## Context

OpenTTD's GameScript protocol is proven but contains OpenTTD-specific transport, identity, save, and
authority assumptions. Rail Route needs a local semantic observation boundary without coupling the
core runtime to Unity or transferring OpenTTD writes.

## Decision

Introduce a separate Sim Pilot Game Bridge Protocol v1 under `sim_pilot.game_bridge`. Use strict
length-prefixed JSON over authenticated loopback TCP, full snapshots only, explicit identity and
coverage, exact version negotiation, delivery sequencing, and resynchronization. Keep Rail Route
translation behind `sim_pilot.rail_route.bridge`. The v1 action catalog is empty.

This milestone does not add `rail_route` to persisted `TaskSpecification.adapter_type`; bridge CLI
observation remains outside the action runtime, just like the existing bounded Rail Route control
proof. A later runtime-adapter expansion requires a separate public-contract decision.

## Consequences

Additional games can implement one wire contract without importing Rail Route models. The direct
TCP server must own authentication and local threat controls that OpenTTD previously supplied.
Protocol versions cannot silently change. No delta, remote transport, or mutation is available in
v1.

