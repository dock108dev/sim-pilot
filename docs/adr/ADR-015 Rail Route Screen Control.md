# ADR-015: Rail Route Screen Control

**Status:** Accepted

## Context

Rail Route 2.3.24 on macOS is a Unity/Mono game with managed assemblies, local saves, and community
map support, but no proven external runtime control API. Its Unity content exposes no useful named
gameplay elements through macOS Accessibility. Sim Pilot needs a terminal-first vertical slice
without modifying the game installation or claiming unverifiable semantic control.

## Decision

The first Rail Route boundary is version-pinned and limited to pause/resume. It observes the
selected time control from a fresh screen capture, sends the game's Space binding through macOS
Accessibility at most once, then independently re-observes and verifies the requested state.

The boundary rejects unknown screens and incompatible versions. It never retries an unverified
input automatically. Natural-language parsing is deterministic and advertises only the proven
actions.

## Consequences

This proves the intended terminal interaction without a game plugin and preserves the runtime's
observe, validate, execute, re-observe, verify discipline. It depends on a stable supported layout
and macOS screen-control permissions.

Named trains, signals, platforms, route-setting, construction, scheduling, and broader automation
remain unsupported. They require a separately designed semantic bridge or another live-proven
boundary with readable postconditions.
