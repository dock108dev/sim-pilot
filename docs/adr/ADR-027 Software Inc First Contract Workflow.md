# ADR-027: Software Inc. First Contract Workflow

- Status: Accepted
- Date: 2026-07-27

## Context

Prompt 5 established team readiness, but a first contract combines volatile market observation,
team suitability, time and financial commitments, several irreversible UI actions, and progress
that unfolds across game time. The semantic bridge must remain read only, while a terminal command
must survive interruption without accepting, promoting, or releasing twice.

Software Inc. 1.8.41 exposes public read state for `ContractWork`, `ContractResult`, `WorkItem`,
`DesignDocument`, `SoftwareAlpha`, `ReviewWork`, `ContractWindow`, work-item GUI controls, and review
setup. Its visible controls can perform the player's actions without granting gameplay-write
authority to the mod.

## Decision

Extend the read-only adapter through version `software-inc-readonly-v8` with complete contract market,
result, UI, work-item, skill, and days-per-month observation. Keep Game Bridge Protocol gameplay
actions empty.

Implement a Software Inc.-specific deterministic contract policy and owner-only SQLite workflow.
This workflow is separate from, and does not imply availability through, the generic task runtime.
Bind its identity to one save, game session, contract, team, and plan fingerprint. Persist each
verified gesture in order.

Treat an available contract's visible `Months` value as a relative completion window. Its public
`Deadline` remains the default 1900 `SDateTime` until work starts and must never be presented as an
absolute deadline. Convert the relative window and observed employee-month workload through the
current save's `DaysPerMonth`; replace it with the observed absolute deadline after acceptance.
Interpret `Any role` only from the employee's observed positive role-skill fields.

Use visible UI only, one gesture per fresh synchronized cycle. Remove unapproved multi-selection
before acceptance. Require separate default-no approval for acceptance, imminent deadline risk,
review spending, promotion, and release. Review approval includes the exact visible configuration
and price. Do not manufacture bugs or wait for a scripted count. Release completion requires the
unique result plus exact payout cash delta, deadline/penalty, and reputation observations. Treat
the exact `Finish` button on a 1.8.41 `DevelopmentContract` as the beta release control. If release
already produced the exact result after an interrupted verification, reconcile it with zero input
instead of retrying the irreversible action.

Add a strict deterministic plain-English parser for this bounded vocabulary. Reject pronouns and
requests that omit the exact team or reward floor instead of asking a model to infer them.

## Consequences

- One suitable first contract can be explained and operated from the terminal while bridge
  mutation authority remains empty.
- Market rows must be visible to be called complete; recommendation may navigate to the Contracts
  window but does not mutate economic state.
- The operator can resume a known workflow after a terminal interruption and refuses stale save,
  session, sequence, row, team, or work-item identities.
- Review initiation is supported only when both a visible work-item control and a completely
  observed cost/configuration exist.
- Current public data supports a conservative deadline budget, not a productivity forecast.
- Prompt 6A was live-promoted after one owner-authorized disposable contract completed through
  release; approval checks remain part of the supported workflow.
