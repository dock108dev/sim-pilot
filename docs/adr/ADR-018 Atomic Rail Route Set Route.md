# ADR-018: Atomic Rail Route `set_route`

**Status:** Superseded by ADR-019; retained as experimental evidence

**Date:** 2026-07-21

## Context

Phase 2 proved typed Rail Route observation on a populated Prague session. Mutation must not be
tested against ordinary gameplay, and the bridge must not become a general remote-control or
reflection surface. The smallest useful semantic action is allocating one route between two named
signals in a disposable Test Yard.

## Decision

Game Bridge Protocol v2 and adapter `rail-route-set-route-v1` advertise exactly one gameplay
capability: `set_route`.

The client authenticates, negotiates the exact catalog, and captures a fresh snapshot. The request
names only an origin signal, destination signal, expected bridge instance, expected game session,
and expected snapshot sequence. The server rejects stale identity or sequence before submission.

On the Unity main thread, the Rail Route adapter resolves each canonical name exactly once using
the public signal `Node.FriendlyName` (falling back to the internal `Node.Name` only when no friendly
name exists) and validates play mode, signal support, existing route/lock/occupancy state, a single interlocking
path, path occupancy/allocation, and Rail Route's public routability predicate. It invokes one typed
route-creation method once. It exposes no arbitrary method name or argument list.

Topology enumeration permits non-free nodes only so discovery cannot misreport a UI route preview
as missing topology. Sim Pilot then rejects every occupied or allocated node explicitly and calls
Rail Route's strict public routability predicate before submission.

The client then captures a fresh snapshot and accepts success only if identities are continuous,
the expected route/allocation appears exactly once, and unrelated active routes are unchanged. An
executed request that cannot be verified is reported as an error and is never retried.

## Consequences

- Route allocation can be driven from deterministic plain English in the terminal.
- Cancellation, dispatch, construction, time control, ongoing automation, multi-action objectives,
  and retries remain unavailable.
- Protocol v1 clients and the v1 read-only adapter are intentionally incompatible with this
  authority boundary.
- Live promotion requires one disposable Test Yard proof; Prague observation is insufficient.

## Supersession

Live attempts were rejected before mutation and showed that direct method invocation was not the
right production boundary. ADR-019 retains the topology findings but moves actuation to the normal
player-visible UI. Protocol v3 removes this request from the installed bridge.
