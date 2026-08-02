# ADR-023: Software Inc. Teams and Hiring

## Status

Accepted for Phase 4. Live authority is promoted action by action only after the disposable-company
gate passes.

## Context

Creating a team is a single gameplay commitment. Hiring is not: Software Inc. can charge for
generating an applicant pool before any candidate or recurring salary is known. Treating a
high-level hire request as one approval would allow an undisclosed search charge or bind approval
to a candidate that did not yet exist.

The existing read-only bridge can verify teams, employees, finances, and exact save/session
identity. The Phase 3 input path can send frame-bound visible gestures but must not use blind
coordinates or bridge mutation methods.

## Decision

- Keep Game Bridge Protocol v3 and the Software Inc. bridge gameplay-action catalog read only.
- Observe active staffing windows, visible applicant identities, labels, costs, selections, and
  normalized UI rectangles on Unity's main thread.
- Require current screenshot evidence for any UI rectangle before it becomes an input target.
- Keep team creation, paid applicant search, and final hire as separate fingerprinted plans.
- Require explicit approval immediately before every gameplay commitment.
- Never combine a one-time search charge and a recurring salary in one approval.
- Select only a visible available Programmer at or below the user's monthly cap; prefer the lowest
  salary and use stable identity as the deterministic tie-break.
- Reject duplicate team names after case-folding and whitespace normalization.
- Send no more than one gesture per cycle and re-observe after every gesture.
- Verify exact semantic deltas for team count, applicant-search cash, employee identity, team
  assignment, salary, target-team headcount, and recurring payroll.
- Never automatically retry an input that may have been sent.
- Retain screenshot-free owner-only staffing traces.

## Consequences

The workflow may ask twice during one hire: once for the known applicant-search charge and again
for the chosen applicant's recurring salary. This is intentional and prevents authority from
expanding as information arrives.

The integration is more sensitive to localized labels and versioned UI hierarchy than a direct
gameplay method, but mutation remains player-visible and independently verifiable. An incomplete
or changed UI blocks instead of falling back to coordinates or semantic method calls.

The initial slice supports one Programmer and one team only. Bulk hiring, other roles, benefits,
specialization, compatibility optimization, firing, team disbanding, and autonomous staffing are
separate future capabilities.
