# Game-Aware Tool Selection Backlog

**Status:** Backlog — no implementation authorized

**Date:** 2026-08-10

## Purpose

Sim Pilot should eventually detect the strongest proven integration surface for the game being
played instead of treating one transport, scripting language, or control method as universal. The
Python runtime remains the game-neutral brain. Each game adapter owns its supported observation and
actuation tools.

This is a deferred capability, not a change to the current product direction. The planned bootstrap
is one explicitly configured Minami Lane application path as the sole startup target. The owner
will configure that default path separately. Until that configuration exists and adapter work is
separately authorized, the current successor-game decision and no-adapter boundary remain in force.

## Invariants

Tool selection must not change the runtime contract:

- one adapter and one task are active at a time;
- each cycle observes, selects one action, validates it, evaluates policy and approval, executes at
  most one action, re-observes, and verifies the effect;
- detecting a tool or capability grants no observation, mutation, spending, or delegation
  authority;
- approval and manual gates remain unchanged and fail closed;
- model output cannot choose or enable a tool directly; selection is deterministic from registered
  adapter metadata and current probe evidence;
- game-specific capability proof is bound to the exact application path, identity, version, and
  session where relevant, and is never inherited by another game;
- a possibly sent action is reconciled before any retry or tool switch.

## Bootstrap boundary

Minami Lane comes first as a fixed, configured target. Its initial adapter remains the smallest
separately authorized vertical slice described in the successor-game decision packet: fresh
exact-window observation, a freshly derived visible target, one ordinary visible click, and a new
capture that verifies the result. Dynamic discovery is not a prerequisite for that loop and must
not broaden it.

The adaptive selector becomes useful only after the fixed Minami Lane loop is valuable and proven.
It should then allow a later game to declare and prove a different native surface without adding
that surface to the Python core as a universal dependency.

## Selection model

Observation and actuation are selected independently because a game's best eyes may not be its best
hands. A registered adapter should expose typed candidate profiles containing:

- game identity and supported version range;
- observation or actuation role;
- official or owner-approved integration surface;
- required files, processes, ports, permissions, mods, or emulator features;
- supported capability catalog and exact schemas;
- read-only probe and health-check procedure;
- freshness, provenance, and postcondition coverage;
- known side effects and approval requirements;
- deterministic priority and fallback rules.

The selector should prefer the most semantic, reliable, officially supported, and least invasive
proven candidate that covers the requested capability. It may compose different tools for
observation and actuation. A nominal API, assembly, socket, save, log, Accessibility tree, or
screenshot facility is only discovery evidence until its exact capability and freshness are
live-proven.

When no registered candidate proves the required capability, Sim Pilot reports `unsupported` or
blocks. It does not install a mod, enable scripting, inject code, attach a debugger, read private
memory, request a broader permission, or fall back to lower-confidence input without separate
owner authorization and adapter-specific proof.

## Illustrative game profiles

These examples guide future adapter design; they are not new roadmap targets or capability claims.

| Game | Likely best proven composition | Boundary |
|---|---|---|
| Minami Lane | Exact-window screenshots, OCR/vision, and ordinary visible clicks | Sole planned configured bootstrap target; no native scripting interface is assumed. |
| Software Inc. | Existing C# read-only semantic bridge plus verified visible UI actions | Frozen reference capability only; its evidence cannot promote another adapter. |
| Factorio | Official game-native Lua mod API for a semantic adapter | Strong future technical surface, but Lua must be enabled and proven for exact capabilities before use. |
| FCEUX/Mario | Emulator-provided Lua API | Illustrative emulator adapter; emulator support does not make Lua a core runtime dependency. |

Lua is therefore one adapter tool when the target natively supports it. Sim Pilot should not add a
generic Lua runtime merely to normalize unrelated games. The same rule applies to C#, JavaScript,
save inspection, Accessibility, screenshots, and OS input.

## Backlog slices

### GTD-000 — Fixed Minami Lane bootstrap

- Accept one explicit owner-configured application path as the only default target.
- Validate exact process, executable, window, and installed-version identity before observation.
- Complete the separately authorized one-capability loop before adding adaptive selection.

### GTD-001 — Typed integration profiles

- Define adapter-owned observation and actuation candidate models.
- Keep required permissions, supported capabilities, trust boundary, and proof status explicit.
- Reject duplicate identities, overlapping priorities, and incomplete fallback definitions.

### GTD-002 — Read-only capability probes

- Probe only registered, already available surfaces without mutation or implicit setup.
- Return typed evidence with source identity, version, freshness, and failure reason.
- Treat permission prompts, missing mods, unknown versions, and ambiguous processes as unavailable.

### GTD-003 — Deterministic selector

- Intersect the task's required capability with live-proven candidates.
- Select observation and actuation independently using versioned deterministic policy.
- Record every considered candidate and the reason it was selected, rejected, or unavailable.

### GTD-004 — Session binding and recovery

- Persist the selected profile, evidence fingerprint, process/session identity, and policy version.
- Re-probe after application-path, version, process, permission, mod, emulator, or session changes.
- Fail closed during recovery when the prior selection cannot be proven equivalent.

### GTD-005 — Second-adapter proof

- Validate the abstraction with one separately selected game whose best surface differs from Minami
  Lane.
- Prove that adding its native tool requires adapter code and registration, not Python-runtime
  policy changes.
- Exercise unavailable, degraded, stale, ambiguous, and post-action reconciliation paths.

## Acceptance gate

This backlog is ready to leave deferred status only when:

1. the owner has configured and selected the single Minami Lane startup target;
2. its first bounded loop has passed live acceptance and is useful in actual play;
3. adaptive selection solves a concrete second-game need rather than anticipating one;
4. the candidate adapter and every required integration surface have separate authorization;
5. typed contracts, deterministic probes and policy, persistence, failure-path tests, Ruff,
   Pyright, pytest, and exact live evidence all pass.

## Non-goals

- changing the current approval or manual gate;
- choosing a game or strategy automatically;
- scanning for and operating arbitrary installed games;
- running multiple game adapters simultaneously;
- treating Lua or any other language as universally preferred;
- installing mods, third-party tools, or permissions automatically;
- converting discovery evidence into execution authority.
