# Software Inc. Prompt 6A First Contract

**Status:** Complete and live-proven on the supported macOS build

## Outcome

Prompt 6A adds a bounded contract-specific objective above the existing read-only bridge and
verified visible-UI controller. Sim Pilot can completely observe the visible contract market,
recommend one suitable contract for an exact team, configure only that contract and team, request
separate approvals at each commitment, advance work in bounded intervals, start an exactly priced
review, promote only when the current UI permits it, and release with financial and reputation
verification.

The semantic bridge remains read only and advertises an empty gameplay-action catalog. Every game
change is made through the same visible controls available to the player. No model output, guide
text, fixed screen coordinate, or private gameplay callback can authorize a contract action.

## Terminal surface

Start with a paused disposable company whose exact team has people, workstations, and the required
roles:

```bash
uv run sim-pilot software-inc crash-course contracts
uv run sim-pilot software-inc contracts browse
uv run sim-pilot software-inc contracts list
uv run sim-pilot software-inc contracts recommend \
  --team Core --minimum-reward 10000 --minimum-cash-reserve 50000
uv run sim-pilot software-inc contracts accept \
  --team Core --minimum-reward 10000 --minimum-cash-reserve 50000
uv run sim-pilot software-inc contracts status
uv run sim-pilot software-inc contracts advance --seconds 10
uv run sim-pilot software-inc contracts review
uv run sim-pilot software-inc contracts promote
uv run sim-pilot software-inc contracts release
```

The same bounded operations have a deterministic plain-English entrypoint:

```bash
uv run sim-pilot software-inc contracts do "browse contracts"
uv run sim-pilot software-inc contracts do \
  "find a small contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts do \
  "accept the recommended contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts do "advance the current contract" --seconds 10
uv run sim-pilot software-inc contracts do "review the current contract"
uv run sim-pilot software-inc contracts do "promote the current contract"
uv run sim-pilot software-inc contracts do "release the current contract"
```

`--dry-run` sends no input. If the requested proof requires first opening a window, dry-run reports
that next reversible gesture and stops instead of silently navigating.

## Observation contract

Adapter `software-inc-readonly-v8` exposes seventeen surfaces. Prompt 6A relies on three new
complete surfaces plus richer existing team, employee, office, finance, company, and game state:

- `contract_market` is complete only while the visible Contracts window is open. Each row includes
  stable identity, display index, client, type/category, features, generated months and development
  time, difficulty, art ratio, minimum progress, quality target, relative completion window, reward,
  maximum penalty, and per-bug penalty. An available `ContractWork` has no absolute deadline yet:
  its default 1900 `SDateTime` is rejected, and the visible Months commitment is normalized through
  the save's observed days-per-month setting. Duplicate identities fail the surface.
- `contract_results` includes exact completed status, date, bugs, payout, final result, bug,
  quality, lateness and cancellation penalties, quality result, and reputation change.
- `contract_ui` identifies the Contracts browser, exact selected rows and teams, team picker,
  current work-item buttons, and review setup. Review mode, count, and visible cost are observed
  before any review commitment.
- `work_items` includes all current work with exact contract linkage, assigned teams, stage,
  progress, minimum progress, deadline, bugs/fixes, quality, beta/release state, review score/count,
  and linked `ReviewWork` identity.

All reads occur on Unity's main thread. The bridge describes callbacks and normalized geometry but
never invokes a callback or gameplay mutation.

## Recommendation policy

The Advisor requires complete current observations and rejects a contract when any of these holds:

1. The exact team is absent or ambiguous.
2. The team has no employees or is missing the applicable Designer, Programmer, or Artist
   coverage. An employee assigned to `Any role` contributes only roles backed by observed positive
   skill values.
3. Attributable valid workspace is below the team's employee count.
4. The team already has active work that accepting the contract would displace.
5. The reward is below the user's exact floor.
6. Reserving the full observed maximum penalty would violate the requested cash reserve.
7. The relative completion window is shorter than the observed employee-month workload converted
   with the current save's days-per-month setting. After work begins, the absolute deadline replaces
   the relative value in the persisted workflow.

Eligible contracts are sorted deterministically by reward, deadline buffer, difficulty, and stable
identity. The Advisor returns one recommendation and no more than two alternatives. If none is
eligible, it reports the observed rejection reasons instead of only a count. It states that future
interruptions, effectiveness, operating expenses, and cash flow are not predicted.

## Execution and approval boundary

Acceptance first removes any other selected contract row and any other selected design or
development team, one fresh visible gesture at a time. The final Accept input is impossible until
the exact recommended row and only the approved team are selected.

Independent default-no approvals bind:

- acceptance to exact contract, client, team, reward, maximum penalty, deadline, reserve policy,
  current save/session, and plan fingerprint;
- each imminent-deadline continuation to that one bounded work interval;
- review to the exact visible internal/client/outsource mode, review count, and one-time cost;
- promotion to the exact current work item and observed stage;
- release to the exact current work item, result rules, and observed deadline.

Approval for one commitment never authorizes another. A stale recommendation, changed save or game
session, non-increasing bridge sequence, ambiguous identity, blocking modal, missing target,
unobserved price, or changed process/window stops before the commitment. A sent but unverified
input is never retried automatically.

## Lifecycle and verification

- `advance` runs for at most 30 real seconds, pauses, and reports observed progress, bugs, and fixed
  bugs. It never waits for or manufactures an arbitrary bug count.
- `review` is supported only during an observed Alpha/Beta stage with a visible review control. It
  opens the setup without spending, observes the exact configuration and cost, asks approval, then
  requires linked review work or a higher completed-review count.
- `promote` requires either observed progress at or above the contract minimum or Software Inc.'s
  exact post-review `Promote to beta` control. Success requires a semantic stage transition.
- `release` requires a current interactable release control. Success requires a unique completed
  result, exact cash delta equal to its observed payout, observed deadline status and penalties,
  and observed post-release reputation. In 1.8.41 the beta release control is labeled `Finish`.
  If input succeeds but terminal verification is interrupted, the next release request binds the
  exact completed result and closes the workflow with zero additional input.

The contract-specific workflow and ordered cycle events are durable in owner-only SQLite at
`~/Library/Application Support/Sim Pilot/software-inc/contracts/workflows.sqlite3`. This does not
claim that Software Inc. is available through the generic persisted-task runtime yet.

## Validation

Default tests cover strict projections, incomplete and duplicate rejection, reward, runway,
deadline, roles, active-work and workspace policy, at-most-two alternatives, stale synchronization,
independent approvals, owner-only persistence, modal rejection, one gesture per fresh cycle,
review cost/configuration binding, linked review verification, plain-English parsing, and the rule
that five bugs are never manufactured.

The repeatable read-only live market/recommendation proof is opt in:

```bash
SIM_PILOT_LIVE_SOFTWARE_INC_CONTRACTS=1 \
SIM_PILOT_SOFTWARE_INC_CONTRACT_TEAM=Core \
SIM_PILOT_SOFTWARE_INC_CONTRACT_MINIMUM_REWARD=10000 \
SIM_PILOT_SOFTWARE_INC_CONTRACT_RESERVE=50000 \
  uv run pytest -m live tests/software_inc/test_live_contracts.py
```

This test authorizes only opening the Contracts window and read-only recommendation proof; it
checks save bytes are unchanged. Economic acceptance, review spending, promotion, deadline risk,
and release remain interactive CLI approvals.

## Current machine evidence

On July 27, 2026, Autosave 1 completed the full gate with Core and the Buzzy Farms Logistics
Application. The contract was recommended and accepted with reward `$12,116`, maximum observed
penalty `$4,022`, and a `$40,000` reserve policy. One review completed with 100% review accuracy;
the exact review result promoted the work to Beta. Sim Pilot then observed 7.2558 natural bugs and
fixed 5.0002 through bounded, re-paused work intervals before using the live `Finish` release
control.

The completed result is `Fulfilled`: payout `$9,166`, final result `$12,116`, late, quality, and bug
penalties `$0`, cash `$60,456`, business reputation `0.201935857534409`, and result reputation
change `1.09507298469543`. A repeated release request was rejected before input because no active
workflow remained. The final read-only proof passed with identical semantic and four-file save
fingerprints across reconnect.

Adapter v8 exposed all seventeen surfaces with an empty gameplay-action catalog. The checksum-
gated release and installed DLL SHA-256 values both equal
`744404855442f4ec30efe53fb3d2df5a19827d8cef9c83423b1834bab508d736`.
The final repository gate passed with 860 tests and 32 explicitly gated live tests skipped. Ruff
formatting and lint, Pyright with zero errors, `uv lock --check`, `git diff --check`, all twelve C#
protocol/server tests, and exact bridge/probe release builds with zero warnings and errors passed.

## Supported boundary

Evidence is pinned to Software Inc. 1.8.41, Steam build 23094975, Unity 2018.4.36f1, Mono x86_64,
English UI, and the current macOS Steam installation. Other versions, languages, stores, Windows,
native ARM64, multiplayer, contract types outside the observed public `ContractWork` lifecycle,
arbitrary team optimization, cancellation, outsourcing configuration, and unattended autonomous
play remain unverified or unsupported.
