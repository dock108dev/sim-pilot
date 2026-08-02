# Software Inc. Phase 4 Teams and Hiring

## Product boundary

Phase 4 adds the first economically meaningful Software Inc. UI workflows:

- create exactly one uniquely named team;
- purchase a bounded applicant search after showing its exact one-time charge;
- observe the complete visible applicant list with stable identities and monthly salaries;
- hire exactly one Programmer into an existing team under an explicit monthly salary cap.

These are player-directed workflows, not autonomous play. The terminal instruction supplies the
team, role, and salary constraint. Sim Pilot chooses only among currently visible eligible
applicants, asks before each commitment, sends at most one gesture per cycle, and verifies every
effect before continuing.

The Guided Operator reports these actions as `offline_integration_tested` and rejects delegation
until the disposable-company live gate succeeds. This document describes the implemented Phase 4
workflow; it does not by itself grant live authority.

The semantic bridge remains read only. Its gameplay-action catalog is empty. Phase 4 expands
observation to `applicants` and `staffing_ui`; it never calls `CreateTeam`, `StartLooking`,
`HireEmployee`, or another gameplay method. All mutations travel through visible game controls.

## Terminal contract

Supported requests are deliberately narrow:

```bash
uv run sim-pilot software-inc ui do "create a team named Support Alpha"
uv run sim-pilot software-inc ui do \
  "observe programmer applicants for Support Alpha under $8,000 per month"
uv run sim-pilot software-inc ui do \
  "hire one programmer for Support Alpha for no more than $8,000 per month"
```

Use `--dry-run` to validate only the next bounded cycle. Dry-run never sends input and never grants
approval.

Hiring requires the singular role `Programmer`, one existing unambiguous team, USD, and an explicit
monthly cap. Team-name comparison collapses whitespace and is case-insensitive, so a request cannot
create a spelling-equivalent duplicate.

## Observation model

The bridge exposes complete teams and employees, including employee team and recurring monthly
salary. While the applicant window is visible, `applicants` is a complete ordered collection:

- stable `NetworkID`;
- display index;
- name;
- role hired for;
- recurring monthly salary;
- wage bracket;
- selected team;
- current availability.

`staffing_ui` contains only read-only presentation state and normalized Unity UI geometry:

- current staffing scene;
- visible team-name field value and focus;
- selected hiring role and wage bracket;
- visible one-time search cost and pool label;
- selected team and applicant indexes;
- active controls, labels, paths, interaction state, and normalized rectangles.

Python maps that geometry into the exact synchronized CoreGraphics capture and accepts a target
only when its current screenshot region is visible. Every target remains bound to the current PID,
window, bounds, scale, frame, scene, projection, and expiration. This avoids fixed blind
coordinates without granting the bridge mutation authority.

## Approval and cost model

Team creation requires approval immediately before the final create click.

A fresh hiring search and a hire are separate commitments:

1. Configure Programmer and the Low wage bracket through the UI.
2. Read the exact visible search charge and pool label.
3. Ask approval for that one-time charge.
4. Re-observe the same session, save, configuration, and cost.
5. Click **Begin looking** once.
6. Verify the exact cash decrease and the resulting applicant collection.
7. Select the lowest-salary eligible Programmer under the user cap, with stable identity as the
   deterministic tie-break.
8. Ask a second approval naming the applicant, stable ID, team, exact monthly salary, and cap.
9. Re-observe the unchanged applicant identity, order, availability, and salary.
10. Click **Hire** once and verify the resulting employee and recurring payroll.

Approval never combines an unknown search fee with an unknown recurring salary. A changed save,
session, applicant, salary, ordering, availability, team, cost, or expired plan invalidates the
approval.

## Verification

Team creation succeeds only when:

- exactly one team identity is added;
- its normalized name equals the approved name;
- employees and unrelated company, office, product, and work-item surfaces are unchanged.

An applicant search succeeds only when:

- team and employee collections are unchanged;
- cash decreases by exactly the approved one-time cost;
- a complete, non-empty visible applicant collection is observed;
- unrelated semantic surfaces remain unchanged.

A hire succeeds only when:

- exactly one employee identity is added and it is the approved applicant;
- role, team, and salary match the approved plan;
- salary is at or below the user cap;
- target-team employee count increases by exactly one;
- total observed recurring payroll increases by exactly that salary;
- no unrelated semantic surface changes.

An input that may have been sent is never retried automatically. Unknown scenes, tutorial or other
blocking modals, ambiguous labels, missing controls, stale frames, and incomplete coverage stop the
workflow.

## Evidence and recovery

Screenshots remain ephemeral. Owner-only staffing traces contain plan fingerprints, approval IDs,
frame and bridge identities, targets, gestures, and verification outcomes:

```text
~/Library/Application Support/Sim Pilot/software-inc/ui/staffing-traces.jsonl
```

The trace does not contain screenshot pixels. Save or reload recovery is intentionally absent:
when an effect is ambiguous, inspect the visible game and semantic state before issuing a new
request.

Phase 4 is pinned to Software Inc. 1.8.41, Steam build 23094975, macOS x86_64, English UI, and the
proven fullscreen capture path. Windows and other versions remain unverified.

## Validation

Offline tests cover strict natural-language parsing, duplicate rejection, applicant coverage,
deterministic selection, paid-search approval and exact cash delta, salary approval drift,
recurring payroll verification, screenshot-bound semantic UI targets, and an end-to-end team
creation state machine with one gesture per fresh cycle. Live promotion additionally requires a
disposable company and explicit approval for the actual team, search charge, and salary.
