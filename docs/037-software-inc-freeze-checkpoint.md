# Software Inc. Freeze Checkpoint

**Status:** Accepted 2026-08-02

## Decision

Software Inc. is frozen as a reference capability. The repository preserves its implementation,
tests, operating guides, ADRs, and validation evidence, but Software Inc. is no longer the default
product roadmap and no further prompt is implied.

No replacement game is selected by this checkpoint. Choosing a game and implementing its adapter
are separate decisions.

## Why the roadmap stops here

Software Inc. proved important engineering boundaries, but basic player objectives quickly expand
into large dependency graphs across skills, teams, rooms, products, stages, costs, and approvals.
That makes it a poor first proof of the simple Sim Pilot experience: type a short objective in a
terminal, watch the game perform an obvious action, and see the result independently verified.

The freeze is a product-direction decision, not a claim that the completed work lacks value.

## Preserved capability

The checkpoint retains:

- game-neutral intent, action, approval, observation, persistence, and verification contracts;
- exact macOS installation and official code-mod lifecycle discovery;
- an authenticated, read-only semantic bridge with an empty gameplay-action catalog;
- fresh exact-window screenshots and current-frame visible-UI targeting;
- one gesture per cycle, re-observation, postcondition verification, and no automatic retry of an
  ambiguous sent action;
- default-no approvals for spending and irreversible commitments;
- bounded time progression with pause restoration;
- owner-only, save/session-bound workflows and fail-closed recovery;
- teacher and advisor paths that cannot silently acquire mutation authority;
- the Software Inc.-specific staffing, office, contract, training, and Atlas implementations and
  their regression tests.

This capability may be maintained and studied. Reusing a game-neutral contract is allowed;
copying Software Inc. screen geometry, mechanics, semantic fields, or live evidence into another
adapter is not.

## Evidence boundary at freeze

The retained documents remain authoritative for their exact evidence. The headline boundary is:

| Slice | Freeze status |
|---|---|
| Official probe and read-only semantic observation | Live-proven on the pinned macOS Steam build |
| `pause`, `resume`, and `open_manage_teams` visible UI | Historical live mutation evidence |
| Guided teaching and advice | Implemented; full live acceptance remains pending |
| Teams and hiring | Offline-tested; not promoted through the Guided Operator |
| Office readiness | Core read paths live-proven |
| Workstation placement | Live-promoted on the pinned disposable company |
| First contract | Live-proven within its exact approvals and supported boundary |
| Three-stage System education | Offline-validated with live safe rejection; no mutating acceptance proof |
| Atlas product through Beta | Offline-validated; no live creation or promotion proof |

Test counts, builds, read-only preflights, and safe rejections are not substitutes for missing live
mutation evidence. Evidence from the pinned game/build does not generalize to another version,
platform, save, or game.

## Checkpoint validation

The 2026-08-02 repository checkpoint passed:

- Ruff formatting and lint across the complete tree;
- Pyright with zero errors, warnings, or information diagnostics;
- pytest with 897 passed and 34 explicitly gated live tests skipped;
- all 12 Game Bridge Core protocol/server checks;
- Rail Route Metadata Catalog and bridge Release builds with zero warnings or errors;
- Software Inc. discovery-probe and read-only-bridge Release builds against the exact installed
  managed assemblies with zero warnings or errors.

The skipped live tests require explicit provider or disposable-game authority. They were not
enabled for this repository checkpoint, and the checkpoint performed no gameplay mutation.

## Next-game selection gate

Before any successor adapter or product UI is implemented, the player must explicitly choose the
game after reviewing one proposed loop that satisfies all of these conditions:

1. The game runs on the player's Mac and is something they want to play now.
2. The opening objective is obvious and completes in a few bounded actions.
3. Sim Pilot starts from the terminal and accepts one short plain-English instruction.
4. A fresh observation identifies one visible target.
5. One ordinary player-visible gesture changes the game.
6. A separate fresh observation independently verifies the postcondition.
7. Spending or irreversible consequences retain explicit approval.

Discovery clues such as test volume, accessibility availability, assemblies, logs, or sockets do
not pass this gate. A dashboard, broad roadmap, or second action is deferred until the first loop is
both technically proven and enjoyable.

## Checkpoint rule

The complete Software Inc. working tree is parked as one reviewed repository checkpoint. Changes
after that checkpoint must begin from a clean tree and must not extend Software Inc. unless the
player explicitly reopens that roadmap.
