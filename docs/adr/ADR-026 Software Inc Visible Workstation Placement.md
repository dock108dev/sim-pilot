# ADR-026: Software Inc. Visible Workstation Placement

- Status: Accepted
- Date: 2026-07-26

## Context

Prompt 5 correctly stopped at an observed workstation shortage because the prior bridge could not
identify a current purchasable bundle, exact price, compatible placement, or safe room-assignment
target. Buying from old guide text or fixed screen coordinates would violate the project's
observable-postcondition and approval rules.

Software Inc. 1.8.41 exposes a read-only furniture catalog, active build preview, room geometry,
camera projection, room context UI, and team selector. Ordinary macOS pointer and keyboard input can
perform the same visible interaction as the player without granting the compiled bridge gameplay
write authority.

## Decision

Keep Game Bridge Protocol gameplay actions empty. Extend only read observation with `build_catalog`
and `build_ui`, including current catalog identity/prices, inventory, snap contracts, active preview
identity/validity, UI geometry, and camera-projected room/furniture points. Never call build,
purchase, assignment, callback, or placement-validation methods from the bridge.

Implement `prepare_team_workstation` as a separate visible-UI capability. Select a minimal compatible
desk/computer/chair bundle deterministically, prefer existing room capacity, reuse verified partial
components, and bind default-no approval to the exact room, team, items, prices, inventory, cash,
reserve, frame, projection, game session, and save.

Normalize recognized non-modal UI state before requesting approval: use only bounded, traced pause
or Escape gestures to reach fresh paused gameplay, then rebuild the plan. Preflight traces have no
approval ID or plan fingerprint. Never ask for approval from a scene that cannot immediately begin
the verified room-assignment workflow.

Treat interactive approval latency as unbounded relative to screenshot lifetime. After approval,
capture a new synchronized frame, require paused gameplay, and compare the full economic and room
commitment while excluding only ephemeral frame/sequence/timestamp fields. Resolve the first and
all subsequent targets from fresh frames; never extend or reuse the pre-prompt target expiry.

Add bounded right-click and pointer-move primitives to the game-neutral computer-control layer.
Pointer movement is not a commitment; a placement click is permitted only after a fresh semantic
observation reports a green preview for the exact approved prefab, price, and room. Preserve one
gesture per cycle and verify exact component identity, capacity, assignment, and cumulative cash
after every commitment.

Never click the builder's initial preview immediately after selecting a palette item. That preview
is created under the palette cursor and can overlap another catalog control while retaining cached
room validity. Move to a fresh camera-projected room or snap-anchor target in one cycle, re-observe
the exact item/price/room/green-preview contract, and only then click that same fresh target in the
next cycle. A placement click without its exact new-equipment postcondition is never retried.

## Consequences

- Sim Pilot can prepare one small team workstation through player-visible controls after exact
  approval while preserving the read-only semantic adapter.
- Layout, resolution, monitor placement, and camera state are handled by fresh projection rather
  than blind coordinates.
- An interrupted setup resumes from valid observed components instead of duplicating purchases.
- Utility cost remains materially unknown; approval reports `$0` fixed recurring cost and observed
  wattage without claiming a monthly electricity estimate.
- The disposable-company acceptance passed on 2026-07-27 for the pinned macOS build: the exact
  `$1,640` bundle produced one valid Core workstation and an independently observed `$48,360` cash
  balance while the simulation remained stopped.
- Existing valid capacity is an idempotent terminal state even when the assigned room reports an
  unrelated major problem; subsequent invocations send no input and cannot purchase a duplicate.
- Construction, relocation, selling, bulk furnishing, server purchase, occupied-room reassignment,
  and autonomous optimization remain unsupported.
