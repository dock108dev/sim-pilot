# ADR-020: Software Inc. Flagship Integration

## Status

Superseded 2026-08-02 by ADR-030. Retained as the historical decision that authorized the
Software Inc. work now frozen as reference capability.

## Context

Sim Pilot's product loop is a local assistant that observes a game, compiles high-level player
intent into bounded actions, executes one validated action per cycle, observes again, and verifies
the result. The deterministic reference simulation, OpenTTD, and Rail Route established reusable
runtime, persistence, approval, bridge, and UI-control boundaries. At the time of this decision,
Software Inc. became the flagship integration.

Software Inc. supplies an official C# code-mod surface through `ModMeta`, `ModBehaviour`, and game
lifecycle events. The installed macOS Steam build is a Unity Mono application, so the official mod
surface can provide semantic observations without memory scraping or arbitrary console execution.
Some future actions may still need verified UI control when the official API lacks a supported,
stable mutation boundary.

## Decision

- `software_inc` is a canonical adapter identifier in the game-neutral domain registry.
- The registry is the sole source of integration availability. Flagship status does not grant
  observation, compilation, runtime, reconciliation, or action authority.
- Prompt 1 implements read-only installation/runtime discovery and a reversible official code-mod
  lifecycle probe only. Its compiler catalog is deliberately empty.
- The probe logs activation, `GameSettings.GameReady`, deactivation, managed thread identity, and
  the game's `Versioning` value. It exposes no transport, semantic snapshot, or gameplay action.
- Probe installation owns exactly one checksum-recorded source file under the official `DLLMods`
  root. It refuses a running game, symlinks, collisions, changed owned files, broad
  `GiveMeFreedom` access, and custom save serialization.
- The official API is preferred for future semantic observation. UI control may be added only as a
  separately discovered capability with fresh preconditions and postcondition verification.
- Arbitrary developer-console commands, reflection-based method execution, memory editing, and
  direct save mutation are outside the production boundary.
- macOS Steam is the first live target. Windows discovery remains an explicit design-only stub
  until independently implemented and proven; macOS evidence must not be generalized to Windows.

## Consequences

Completed generic infrastructure remains intact and older integrations remain usable. Software
Inc.-specific code lives below `sim_pilot.software_inc` and `software_inc_bridge`; architecture
tests prevent it from entering the domain, runtime, persistence, bridge-client, or computer-control
packages. Gameplay authority remains empty until later prompts define typed observations and then
individually prove actions.

The public modding wiki is useful design guidance, but the installed managed assemblies are the
compatibility authority. The probe must compile against the exact local assemblies before live
installation because released builds can differ from wiki examples.

## References

- [Software Inc. code modding](https://softwareinc.coredumping.com/wiki/index.php/Code_Modding)
- [Software Inc. modding](https://softwareinc.coredumping.com/wiki/index.php/Modding)
- [Software Inc. console](https://softwareinc.coredumping.com/wiki/index.php/Console)
- [Software Inc. Alpha 10 guide](https://steamcommunity.com/sharedfiles/filedetails/?id=1524036140)
