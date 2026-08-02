# ADR-028: Software Inc. First Training Assignment

- Status: Accepted
- Date: 2026-07-27

## Context

Prompt 6A proved one contract, and the next beginner objective is a three-month System-design
training assignment for Core. Training temporarily removes an employee from productive capacity,
charges cash immediately, keeps payroll running, advances over game time, and is easy to duplicate
after a terminal interruption. Guide wording does not match the current game's exact API: Software
Inc. calls the mechanic Education and models System design as the Designer role plus System
specialization.

The semantic bridge must remain read only. The visible UI must remain the player-visible mutation
boundary, and no time-advance command may leave the game running after an interruption.

## Decision

Extend the read-only adapter to `software-inc-readonly-v9` with complete `education` and
`education_ui` surfaces and public active-course fields on employees. Read
`EducationWindow.EducationMonths`, `EducationWindow.GetEducationCost`, specialization levels,
course pairs, and normalized UI geometry only on Unity's main thread. Keep protocol gameplay
actions empty and never invoke Education callbacks or mutation methods from the bridge.

Support a three-month objective as three sequential one-month `Designer:System` courses from level
0 to the level-3 maximum. Use the version-pinned $600, $2,000, and $5,000 schedule for projection,
but rebind the current price to live state before every commitment. Require an exact team and
user-supplied cash reserve. Reject active education, employees above level 0, observed work
displacement, and projected reserve violations. Disclose direct cost, continuing payroll, capacity
before and during absence, and material unknowns.

Persist a Software Inc.-specific owner-only workflow until the generic task runtime is composed for
this adapter. Bind it to save, game session, employee, team, role, specialization, duration, initial
initial and target levels, projected and actual prices, completed stages, reserve, and a
deterministic fingerprint. Permit only one open training workflow per save.

Use visible UI only, one gesture per fresh synchronized cycle. Require fresh default-no approval
for each exact one-month Education commitment. Verify the exact active course and exact cash delta.
Reconcile a duplicate active course or completed level gain with zero input instead of repeating a
commitment, and suspend between levels for the next current-cost approval.

Advance game time in caller-selected intervals of at most 30 real seconds. Start from paused
gameplay and use shielded finally-style cleanup after resume so interruption still triggers a fresh
observation and pause. Declare a course complete only after it disappears with exactly one System
level increase; declare the objective complete only at level 3 after all three courses.

## Consequences

- The user's plain-English System-design objective has one deterministic current-version mapping.
- Teacher and Advisor paths remain read-only and cannot create approval or send UI input.
- The bridge grows semantic observation without gaining gameplay-write authority.
- Education spending and temporary capacity loss are explicit at approval time.
- Long game-time waits require repeated bounded operator cycles; unattended autonomous progression
  remains unsupported.
- Other education domains require separate semantic, UI, policy, and live evidence before
  promotion.
