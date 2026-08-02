# Software Inc. Prompt 7 First Product: Atlas

**Status:** Frozen reference capability. Implemented and offline-validated; live creation and
promotion were not proven before the 2026-08-02 roadmap freeze.

## Outcome

Prompt 7 adds one deliberately bounded product-development objective:

> Begin a small game engine called Atlas, use Core, and keep projected cash above $50,000.

Sim Pilot can teach the current supported product workflow, inspect the current Game Engine
catalog and New software design window, recommend or reject the exact visible configuration,
create one persisted Atlas workflow, hold or resume the exact project, run short work intervals,
start and reconcile reviews, iterate, and promote through Design, Alpha, and Beta. It does not
release the product. Release, marketing, support, distribution, returns, and revenue remain outside
the frozen boundary; no Prompt 8 is authorized.

The semantic bridge remains read only and advertises `gameplay_actions=[]`. Every gameplay change
is ordinary player-visible UI input against a fresh synchronized screenshot and semantic snapshot.

## Supported terminal surface

Start with Software Inc. 1.8.41 loaded into a disposable company and paused:

```bash
uv run sim-pilot software-inc crash-course products
uv run sim-pilot software-inc crash-course development
uv run sim-pilot software-inc ask "How does product development work?"

uv run sim-pilot software-inc products types
uv run sim-pilot software-inc products features --type "Game Engine"
uv run sim-pilot software-inc products operating-systems
uv run sim-pilot software-inc products recommend --minimum-cash-reserve 50000

uv run sim-pilot software-inc products start --minimum-cash-reserve 50000 --dry-run
uv run sim-pilot software-inc products start --minimum-cash-reserve 50000
uv run sim-pilot software-inc products status
uv run sim-pilot software-inc products advance --seconds 10
uv run sim-pilot software-inc products review
uv run sim-pilot software-inc products iterate
uv run sim-pilot software-inc products promote
uv run sim-pilot software-inc products hold
uv run sim-pilot software-inc products resume
```

The strict plain-English entry point is:

```bash
uv run sim-pilot software-inc products do \
  "begin a small game engine called Atlas using Core and keep $50,000 in reserve"
uv run sim-pilot software-inc products do "status Atlas"
uv run sim-pilot software-inc products do "advance Atlas" --seconds 10
uv run sim-pilot software-inc products do "review Atlas"
uv run sim-pilot software-inc products do "iterate Atlas"
uv run sim-pilot software-inc products do "promote Atlas"
uv run sim-pilot software-inc products do "hold Atlas"
uv run sim-pilot software-inc products do "resume Atlas"
```

The interactive `/operate` route accepts the same Atlas vocabulary. Unsupported names, product
types, teams, releases, vague pronouns, or open-ended optimization requests fail before input.

## Current-version observation contract

Adapter `software-inc-readonly-v10` exposes twenty-one semantic surfaces. Prompt 7 adds:

- `product_catalog`: current software types, categories, feature dependencies, specialization,
  development-time value, code/art ratio, server requirement, unlock state, and public price/type
  metadata;
- `product_ui`: exact visible design page, name, type, category, price, selected features,
  available and selected operating systems, selected design/development teams, team warning,
  team-picker state, and normalized current-frame controls;
- `products`: one stable entity per released company product instead of the former count-only
  summary;
- richer `work_items`: the existing current-version design, development, review, progress,
  iteration, pause, Alpha/Beta, and exact control observations shared with contracts.

All game APIs are read on Unity's main thread. The bridge does not call a design, work-item,
review, promotion, pause, or UI mutation method. UI control remains a separate capability catalog.

## Teacher

The checked-in Software Inc. knowledge catalog adds `products` and `development` topics for the
pinned 1.8.41 workflow. It explains the supported catalog evidence, dependencies, team and skill
requirements, Design-to-Alpha progression, reviews and iterations, Beta boundary, OS and price
placement, and conservative runway. The catalog does not turn an old guide's ordering into current
fact. Teacher questions and crash courses never create a workflow, request approval, or send input.

## Advisor and runway policy

The Advisor evaluates only the exact configuration currently visible in the New software design
window. A recommendation requires:

1. exact product name `Atlas`;
2. current unlocked type `Game Engine`;
3. at least one selected current-catalog feature and operating system;
4. exactly `Core` for design and development;
5. observed Programmer and Designer skill and no existing active Core work;
6. no game-reported team issue;
7. no selected feature with an unsupported non-zero server requirement;
8. a projected cash result at or above the requested reserve.

The conservative period is the rounded-up sum of selected features' observed development-time
values, with at least one month. Every observed employee salary and infrastructure recurring cost
continues for that period. Known immediate product charges are included when observable. Forecast
sales, future contracts, investment, loans, and other speculative income are always zero. Material
unknowns are returned with the recommendation.

This is an intentionally strict solvency bound, not a duration or revenue forecast. If it rejects
the current save, the supported response is to earn cash, lower cost, or explicitly select another
configuration; Sim Pilot does not weaken the $50,000 policy or assume Atlas will sell.

## Approval and execution

The owner-only workflow is stored at:

```text
~/Library/Application Support/Sim Pilot/software-inc/products/workflows.sqlite3
```

Its directory is mode `0700` and database is mode `0600`. One open product workflow may own a save.
The workflow binds the exact game session, save identity, product name/type/category, selected
features and operating systems, team, price, reserve, initial and projected cash, stage, work-item
identity, iteration, progress, pause state, configuration fingerprint, and increasing bridge
sequence. Ordered verified cycle events contain metadata but no screenshot pixels.

Reversible setup may navigate pages, edit the exact name, choose catalog entries, and reduce both
team selections to Core. Each gesture uses only its current frame and is followed by a new
observation. Before the final design click, Sim Pilot creates an exact default-no approval and then
re-observes the full configuration, team suitability, runway, session, save, and control. A change
during approval invalidates it.

Creation succeeds only when one new exact Atlas Design work item is observed, cash did not increase
unexpectedly, the reserve still holds, and the game remains paused. An unapproved warning or charge
is left untouched. An existing Atlas reconciles with zero gestures only when its persisted workflow
and exact save/session identity are present; adoption of unknown work is not authorized.

## Controlled progression

- `advance` accepts 0–30 real seconds, starts only from pause, and uses shielded cleanup to return
  to pause even on interruption. A fresh semantic observation records actual progress or stage.
- `hold` and `resume` target only Atlas and verify the work item's exact `paused` state.
- `review` observes the live review setup and exact cost, checks reserve, requests approval, and
  verifies a review linked to Atlas.
- `iterate` is available only from the exact paused Atlas review result, requests fresh approval,
  and requires the observed iteration to increase.
- `promote` rechecks the full remaining runway, team and prerequisite state, displays the expected
  transition, requests fresh approval, and verifies Design→Alpha or Alpha→Beta. Confirmation
  dialogs are accepted only when bound to that immediately preceding approved transition.
- Beta is terminal for Prompt 7. A repeated promotion sends zero input and explicitly reports that
  release is outside the supported boundary.

## Failure and recovery

Stale frames, duplicate targets, unsupported scenes, modal dialogs, changed window/process,
changed save/session/bridge identity, non-increasing sequence, missing catalog fields, ambiguous
work, unknown stage, changed approval state, insufficient reserve, and unverifiable postconditions
all fail closed. A possibly sent but unverifiable commitment is not retried. Operators report
partial progress and leave the game paused wherever the bounded cleanup contract applies.

## Validation

Default tests cover catalog projection, exact configuration, safe and rejected recommendations,
zero forecast revenue, staged approvals, Design/Alpha/Beta reconciliation, owner-only persistence,
strict intent parsing, dry-run and denial zero-input behavior, one-click verified creation,
duplicate rejection, and separate approved promotions through Beta. The bridge is compiled against
the exact installed managed assemblies and the source guard continues to reject gameplay mutation.

Live checks remain explicitly opt-in and must use a disposable save. They first prove the read-only
preflight and save fingerprint. Product creation and later stage approvals are separate material
commitments; never treat a preflight or safe reserve rejection as proof that Atlas reached Beta.
