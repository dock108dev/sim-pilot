# Software Inc. Prompt 6B First Training Assignment

**Status:** Implemented and offline-validated; live safe-rejection/read-only proof passed. Mutating
acceptance requires a disposable level-0 Designer/System employee.

## Outcome

Prompt 6B adds one narrowly defined education objective above the read-only Software Inc. bridge
and visible-UI controller:

> Train one suitable employee from Core in System design for three months while keeping $50,000
> in cash.

Software Inc. 1.8.41 calls this mechanic **Education**. The supported phrase **System design** maps
to the exact `Designer` role and `System` specialization. Each course lasts one in-game month and
grants one specialization level, whose maximum is 3. The objective is therefore three sequential
courses from level 0 through level 3, with verified direct costs of $600, $2,000, and $5,000. Sim
Pilot projects all three charges, then asks for fresh default-no approval at each level. Time
advances only in bounded intervals that finish paused.

The semantic gameplay-action catalog remains empty. The bridge reads public game and UI state on
Unity's main thread but never invokes an education method, callback, or gameplay mutation.

## Terminal surface

Start with the supported disposable company loaded and paused:

```bash
uv run sim-pilot software-inc crash-course training
uv run sim-pilot software-inc ask "How does training work?"
uv run sim-pilot software-inc ask "What is System design?"

uv run sim-pilot software-inc training recommend \
  --team Core --minimum-cash-reserve 50000
uv run sim-pilot software-inc training start \
  --team Core --minimum-cash-reserve 50000 --dry-run
uv run sim-pilot software-inc training start \
  --team Core --minimum-cash-reserve 50000
uv run sim-pilot software-inc training status
uv run sim-pilot software-inc training advance --seconds 10
```

The same bounded vocabulary is available through plain English:

```bash
uv run sim-pilot software-inc training do \
  "recommend one suitable employee from Core for System design education while keeping $50,000 in cash"
uv run sim-pilot software-inc training do \
  "train one suitable employee from Core in System design for three months while keeping $50,000 in cash"
uv run sim-pilot software-inc training do "advance training" --seconds 10
uv run sim-pilot software-inc training do "training status"
```

`start --dry-run` sends no input. A live `start` may perform reversible navigation before the
approval prompt, but an Education commitment cannot be clicked until the exact employee, role,
specialization, one-month duration, level transition, price, cash outcome, reserve, and continuing
payroll are shown and approved. Run `advance` until the course ends, then `start` again for the next
fresh approval. Completion is level 3 after all three courses. Each invocation advances no more
than 30 real seconds and returns the game to pause.

## Observation contract

Adapter `software-inc-readonly-v9` exposes nineteen complete observation surfaces. Prompt 6B adds:

- `education`: the game-owned education duration plus every employed actor's public role and
  specialization levels and the exact current one-time price returned by
  `EducationWindow.GetEducationCost`;
- `education_ui`: exact selected employees, role, specialization, duration, price, combo contents,
  visible start label, and normalized current-frame targets for employee rows, role and
  specialization selectors, and the final Education button;
- richer `employees`: `TakingCourses`, the exact active role/specialization course pairs, and the
  last course marker.

The operator also requires complete current `teams`, `work_items`, and `employees` observations and
observed current cash. Missing, partial, duplicate, non-finite, stale, or cross-save data fails
before input.

## Teacher and Advisor

Version-pinned knowledge explains the Education model, the supported System-design mapping,
selection policy, direct cost, continuing payroll, temporary capacity loss, and the boundary of
the productivity claim. Questions and crash courses have no UI-execution dependency and send zero
gestures.

The deterministic Advisor:

1. resolves one exact team and verifies the game's one-month-per-course duration;
2. considers exact employees with an observed Designer/System specialization;
3. rejects an employee who is already taking any course;
4. rejects a plan that would displace observed active team work;
5. rejects an employee above level 0 because three more courses would exceed level 3;
6. rejects the projected $7,600 curriculum when it would take cash below the reserve;
7. sorts eligible candidates by observed Designer skill, current specialization level, direct
   cost, and stable employee identity;
8. returns one recommendation and no more than two alternatives.

A one-person team is not fabricated as ineligible merely because capacity temporarily becomes
zero. That opportunity cost is disclosed in both the recommendation and approval. The Advisor does
not predict the exact productivity benefit of a new specialization level or complete future cash
flow.

## Approval, execution, and verification

The owner-only workflow binds one save, game session, exact employee, team, Designer/System,
three-course curriculum, initial and target levels, projected and actual costs, reserve, and plan
fingerprint. It is stored at:

```text
~/Library/Application Support/Sim Pilot/software-inc/training/workflows.sqlite3
```

The directory is mode `0700` and the database is mode `0600`. Only one open education workflow may
own a save. Ordered cycle events record verified progress without screenshot pixels.

Starting education keeps the game paused while it navigates Employees and Education. Each cycle
sends at most one gesture against a fresh synchronized frame and then re-observes. Every final
click requires a fresh post-approval observation proving the same exact employee, Designer/System,
one-month duration, current level, and price. Success requires both the exact active course and a
cash delta equal to that stage's approved cost. A duplicate start reconciles with zero input, no
new approval, and no second charge. Course completion suspends for the next approval.

Progression begins only from paused gameplay. It closes only a reversible management window,
resumes, remains foreground for the requested bounded interval, and uses shielded finally-style
cleanup to pause even when foregrounding or waiting is interrupted. Each course must disappear
with exactly one System specialization gain; the objective completes only after three approved
courses reach level 3. Course disappearance without that gain is a verification failure.
Repeating an already-completed advance sends zero input.

## Validation

Default tests cover complete-surface projection, exact phrase parsing, one-month-course
enforcement, three-stage projection, maximum-level rejection, candidate sorting, alternatives,
active-course, active-work, reserve and identity rejection,
separate direct/continuing cost disclosure, exact approval binding, owner-only persistence,
reconnect reconciliation, duplicate-start idempotence, modal/stale-target rejection, one gesture
per fresh cycle, exact cash/course verification, bounded completion, and interruption-safe pause.

The opt-in live test navigates only to the exact pending approval, sends no commitment click, and
proves unchanged save bytes:

```bash
SIM_PILOT_LIVE_SOFTWARE_INC_TRAINING=1 \
SIM_PILOT_SOFTWARE_INC_TRAINING_TEAM=Core \
SIM_PILOT_SOFTWARE_INC_TRAINING_RESERVE=50000 \
  uv run pytest -m live tests/software_inc/test_live_training.py
```

The gate does not approve or start Education. Complete each economic commitment through the
interactive terminal command so the exact current employee, level, and price are visible.

On July 27, 2026, the live v9 bridge proved the corrected mechanic, safe policy, and non-mutation
boundary. Core's only employee, Gage Chen, was already Designer/System level 3, so the advisor
rejected three additional courses with zero gestures. The game remained paused, gameplay actions
remained empty, semantic fingerprints matched, and all four save-file fingerprints remained
unchanged. This is valid rejection evidence, not a mutating acceptance claim.

## Supported boundary

Evidence is pinned to Software Inc. 1.8.41, Steam build 23094975, Unity 2018.4.36f1, Mono x86_64,
English UI, and the current macOS Steam installation. Other role/specialization pairs, custom
durations, employees starting above level 0, multiple simultaneous courses, training cancellation, choosing based on predicted
productivity, unattended long-running time progression, Windows, native ARM64, other languages,
stores, or game versions are unsupported.
