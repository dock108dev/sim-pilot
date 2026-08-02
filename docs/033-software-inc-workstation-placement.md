# Software Inc. Prompt 5B Workstation Placement

**Status:** Live promoted on the pinned macOS build (2026-07-27)

## Outcome

Prompt 5B closes the purchase-and-placement gap left explicit by Prompt 5. Sim Pilot can derive the
smallest compatible workstation bundle from the current Software Inc. 1.8.41 furniture catalog,
request an exact itemized approval, assign an empty room to one exact team, and place the approved
desk, computer, and chair through ordinary visible game controls.

The semantic bridge stays read only and its gameplay-action catalog stays empty. It observes the
catalog, active build/search state, room/team selector, current preview validity, and camera-projected
world targets. Python sends the same bounded mouse and keyboard input a player would send.

## Terminal surface

With Software Inc. open on a paused disposable company:

```bash
uv run sim-pilot software-inc office readiness Core

uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve" \
  --dry-run

uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve"
```

The dry run sends no input. The live form prints the exact room assignment, reused components,
catalog names, prefab identities, quantities, current prices, inventory use, exact cash charge,
projected cash, fixed recurring cost, wattage, and material utility-cost unknown before default-no
confirmation.

## Observation contract

Adapter `software-inc-readonly-v4` adds two complete surfaces:

- `build_catalog` lists every currently queryable furniture item with its exact localized global
  search title, prefab identity, current public-API price, inventory count, furniture type,
  assignment/chair contract, snap compatibility, indoor/outdoor validity, wattage, computer power,
  and search availability.
- `build_ui` observes the active gameplay, global-search, build, furniture-preview, room-context,
  and room-team-selection scenes. It exposes current search text/results/focus, exact active builder
  identity and price, preview room and green/red validity, selected room teams, visible controls,
  placed-furniture anchors, and up to 64 visible candidate points per player-owned active-floor room.

Room and furniture world positions are projected using the game's read-only camera API and then
corroborated against the fresh exact-window screenshot. The bridge never invokes a UI callback,
placement check, purchase method, room assignment, or other gameplay mutation.

## Deterministic planning

The planner requires one uniquely observed team with at least one member, complete room and catalog
coverage, current cash, one exact game session/save, and a synchronized screenshot projection. It:

1. Prefers a room already assigned to the team.
2. Otherwise selects an empty player-owned indoor room and refuses to evict another team.
3. Stops if the room already has a valid workstation.
4. Selects the cheapest uniquely searchable assignable Computer that requires a chair.
5. Selects the cheapest desk/table with a compatible Computer snap point.
6. Selects the cheapest chair compatible with that surface.
7. Reuses exact valid, unblocked components already present in the room after an interrupted run.
8. Charges only for missing components, including observed inventory deductions.
9. Rejects the plan before approval when projected cash would violate the requested reserve.

Catalog identity, item price, inventory, cash, room assignment, bridge sequence, frame, projection,
game session, and save identity bind the five-minute approval. Any cash or catalog change invalidates
it and requires a fresh plan.

Before approval, the live operator performs a bounded reversible preflight. It pauses running
gameplay and closes recognized non-modal management/build/contract scenes through their exact
visible controls (or a verified Escape transition where applicable) until a fresh paused-gameplay
observation is reached. Every preflight gesture is traced without an approval identifier. Only then
does it rebuild the exact plan and ask for approval; an earlier plan or approval is never carried
across scene cleanup.

After the user answers the approval prompt, the operator takes another synchronized observation
before resolving any target. It revalidates the complete non-ephemeral commitment—save/session,
team, room, assignment, existing components, catalog identities and prices, cash, reserve, and
costs—against the approved plan. The fresh frame and projection supply the click targets; the
pre-prompt screenshot is never reused after an interactive wait.

## Execution and verification

The operator keeps the simulation paused and sends at most one gesture per cycle. Every gesture is
followed by a fresh screenshot and a strictly increasing semantic snapshot.

- An empty room is right-clicked only at a fresh camera-projected point.
- `Change Room Team` and the exact team are selected from current visible controls.
- Each catalog item is selected through its exact current visible build-palette control. Missing or
  offscreen catalog controls stop rather than trigger guessed scrolling or a blind shortcut.
- Pointer movement is preview-only and never spends money.
- A newly selected item is always moved from the palette to a fresh room or snap-anchor target in a
  separate cycle. The initial builder preview under the palette cursor is never clicked, even if the
  game reports a cached green preview.
- Placement click is permitted only after the bridge observes a green preview, the exact approved
  prefab and price, and the exact target room.
- Computer and chair placement first try the newly placed or safely reused desk as a snap anchor.
- Each item is verified by exact new prefab identity and exact cumulative cash change before the
  next item begins.
- Completion requires the requested team on the room, no unrelated team change, at least one valid
  workstation, exact cash delta, and a still-paused simulation.

If the process stops after a verified component placement, a new invocation observes and reuses
that exact valid component. It will not buy the same desk, computer, or chair again. An ambiguous
input outcome is never automatically repeated inside an invocation.

If the requested team already has a valid observed workstation, the command completes idempotently
with zero approval prompts, zero gestures, and zero additional spending. This check takes precedence
over unrelated room-problem flags so the planner cannot furnish a second room by mistake.

## Safety boundary

- Every purchase and room assignment requires default-no approval for the exact current plan.
- Closing a recognized non-modal window and pausing are reversible preflight actions. They occur
  before plan construction and approval and cannot authorize room assignment or furniture input.
- Fixed recurring monthly cost for this local furniture slice is `$0.00`; electricity remains an
  explicitly unknown usage-based cost even though wattage is observed.
- No furniture is moved, replaced, sold, or removed.
- No occupied room is reassigned and no unrelated team is changed.
- No item is bought solely because a historical guide recommends it.
- A red/unknown preview, stale frame, modal, offscreen point, display gap, session/save drift,
  catalog drift, cash drift, or missing postcondition stops execution.
- Servers, construction, bulk furnishing, employee desk ownership, and arbitrary optimization remain
  outside this slice.

## Validation

Default tests cover exact compatible-bundle selection, reserve rejection, approval identity/cash
binding, exact cash/capacity verification, interrupted-run reuse, denied approval, dry-run zero
input, semantic camera projection, point safety, right-click/move dispatch, and the existing
Software Inc. regression suite.

The explicit destructive acceptance is:

```bash
SIM_PILOT_LIVE_SOFTWARE_INC_WORKSTATION=1 \
SIM_PILOT_SOFTWARE_INC_WORKSTATION_TEAM=Core \
SIM_PILOT_SOFTWARE_INC_WORKSTATION_RESERVE=49000 \
  uv run pytest -m live tests/software_inc/test_live_workstation.py
```

That environment gate is test-only. It is an explicit authorization to buy and place the printed
bundle in a disposable company; it is not a general runtime write-enable switch.

### Live evidence

The pinned live acceptance used the exact terminal request:

```bash
uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $48,000 in reserve"
```

The default-no approval named room 3 and authorized exactly one Corner Table at `$90`, one Old
Computer at `$1,500`, and one Plastic Chair at `$50`—`$1,640` total, `$48,360` projected cash, and a
`$48,000` reserve. The operation completed in 15 cycles and 11 gestures. An independent synchronized
observation then reported room 3 assigned only to Core, all three exact prefab identities valid and
unblocked, one valid/available workstation, six total room objects, simulation speed `0`, and cash
`$48,360`. A second non-dry invocation completed with zero gestures and no approval, proving the
duplicate-purchase guard.

## Supported boundary

Evidence is pinned to Software Inc. 1.8.41, Steam build 23094975, Unity 2018.4.36f1, Mono x86_64,
English UI, and the current macOS Steam installation. Other versions, languages, stores, Windows,
native ARM64, different camera/build-mode behavior, and mod interactions remain unverified.
