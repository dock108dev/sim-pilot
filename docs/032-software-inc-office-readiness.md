# Software Inc. Prompt 5 Office Readiness

**Status:** Prompt 5 core live-proven; purchase/placement boundary continued in Prompt 5B

Prompt 5B now supplies the exact catalog and visible placement boundary that this milestone left
open. Current workstation commands and evidence are documented in
[033-software-inc-workstation-placement.md](033-software-inc-workstation-placement.md). The remainder
of this file records the Prompt 5 gate and the evidence that justified stopping before 5B.

## Outcome

Prompt 5 adds a version-pinned office-readiness model, Teacher and Advisor coverage, and bounded
visible-UI operators for team schedules and employee roles. The semantic bridge remains read only
and advertises an empty gameplay-action catalog.

The live disposable company proves the safe core but also exposes a real gate condition: Core has
one employee and zero valid workstations. Sim Pilot reports that shortage exactly. It does not claim
the company is ready or buy an arbitrary desk because the current observation still lacks an exact
purchasable catalog item and placement tile. This is an explicit partial-completion result required
by the Prompt 5 safety contract, not a fabricated gate pass.

The implementation is deliberately narrower than the old Alpha 10 guide. Software Inc. 1.8.41 is
the authority for observed state and UI behavior. The guide's SCM-server recommendation is retained
as historical provenance, not promoted into a current prerequisite.

## Terminal surface

```bash
uv run sim-pilot software-inc office readiness Core
uv run sim-pilot software-inc office readiness Core --json

uv run sim-pilot software-inc ask "Does Core have enough desks?"
uv run sim-pilot software-inc ask "What hours does Core work?"
uv run sim-pilot software-inc ask "What office equipment are we missing?"
uv run sim-pilot software-inc ask "Does this team need a server?"

uv run sim-pilot software-inc crash-course office
uv run sim-pilot software-inc crash-course schedules
uv run sim-pilot software-inc crash-course roles
uv run sim-pilot software-inc crash-course servers

uv run sim-pilot software-inc ui do "set Core working hours to 8-16" --dry-run
uv run sim-pilot software-inc ui do "assign Gage Chen as Programmer for Core" --dry-run
```

`readiness` and every question/course are read-only. A schedule or role instruction must name one
exact team; a role instruction must also name one exact employee and one of Lead, Programmer,
Designer, Artist, or Service. The schedule is limited to whole hours, an increasing interval, and
at most twelve hours.

## Observation model

The Prompt 5 bridge snapshot exposed twelve surfaces. Prompt 5 added complete `offices`,
`infrastructure`, and `office_ui` coverage to the previously proven company model. Prompt 5B keeps
the adapter name `software-inc-readonly-v4` and expands the current total to fourteen.

For every player-owned indoor room, the bridge observes:

- stable room network identity, floor, area, assigned teams, occupants, and furniture count;
- lighting, temperature, acoustics, environment, problem count, and major-problem state;
- valid, available, and total workstation capacity.

For every placed furniture item it observes the session identity, exact game name, placement room,
assignment and owner state, validity and obstruction, `NeedsChair`, actions and categories,
computer power, wattage, comfort, environment, and one-time item cost. `CanAssign` alone is not a
workstation signal: the live game also sets it for personal facilities such as toilets. Prompt 5
therefore counts only valid, unblocked items for which both `CanAssign` and `NeedsChair` are true.

Infrastructure exposes every current server group with name, cloud state, available capacity,
fault state, item/server counts, recurring group cost, and power. The empty collection is a valid
complete observation.

`office_ui` and `staffing_ui` expose active management scene, selected team and employees, schedule
field values/focus, role toggle state, and current Unity control geometry. Read-only persistent
button callback names are included as target evidence. They are never invoked by the bridge.

## Readiness and advice

Readiness compares exact observed team membership with the supported workstation proxy in rooms
assigned to that team. It reports:

- current and required capacity and the exact shortage;
- assigned room facts and placed equipment;
- unassigned rooms with valid existing capacity;
- expected benefit;
- one-time and recurring costs when actually known;
- observed cash and projected cash after a known commitment;
- all current server groups;
- material unknowns.

The Advisor prefers existing unassigned capacity over a purchase. It does not invent a furniture
catalog price, placement tile, utility bill, productivity threshold, or server prerequisite. A
recommendation may say that a workstation is missing without guessing which purchasable desk is
best.

## Visible-UI operators

Schedule and role control preserve the Phase 3 execution contract:

1. Re-observe the exact game, session, save, process, window, screenshot, and semantic state.
2. Keep the simulation paused.
3. Resolve one target from current Unity geometry and current screenshot pixels.
4. Send at most one click, key chord, or text gesture.
5. Re-observe before selecting the next action.
6. Verify exact team hours or exact employee identity and role.
7. Stop on a modal, ambiguous target, stale frame, identity drift, or uncertain effect.

An already-satisfied request is a verified zero-input success. A possibly sent but unverified input
is never resent. If Unity commits a window change after the first synchronized sample, one bounded
additional observation may verify the effect without sending another gesture.

The macOS control backend now supports signed global coordinates and enumerates every active
CoreGraphics display. Before each capture it verifies that the full game window is contained by the
primary display. An overflowed or cross-monitor window that fits is moved once, then re-resolved by
PID, window ID, content bounds, visible regions, display IDs, and scale. A larger-than-display window
fails closed. Targets in offscreen areas or display gaps are never eligible for input.

Room/team assignment, employee/workstation assignment, furniture placement, and server creation
were not advertised as direct UI actions in this revision. That Prompt 5 boundary failed closed
instead of evicting a team, relocating furniture, or buying from guide text. Prompt 5B separately
adds one exact workstation/empty-room workflow; employee ownership, relocation, and server creation
remain outside the supported catalog.

## Approval boundary

`OfficePurchaseApproval` is the strict commitment contract for any later purchase path. Approval
must bind exact item name, quantity, unit and total price, projected cash, minimum reserve, recurring
monthly cost, and separate recurring-cost authority. A mismatched total, violated reserve, or
unauthorized recurring cost is rejected before input.

No Prompt 5 command reached that approval because the required live catalog and placement target
were unavailable. Prompt 5B supersedes this narrow deferral with a plan-bound default-no approval;
opening a window or inspecting furniture still never grants purchase authority.

## Validation

Normal tests cover parsing, ambiguity and unsafe-hour rejection, exact readiness, reuse-before-buy,
server non-inference, exact purchase approval, schedule and role postconditions, zero-input
idempotence, semantic gameplay-toolbar targeting, questions, crash courses, and the delegation
boundary.

The opt-in disposable-save acceptance is:

```bash
SIM_PILOT_LIVE_SOFTWARE_INC_OFFICE=1 \
  uv run pytest -m live tests/software_inc/test_live_office.py
```

It passed against the paused `Company Name Here` disposable company. It verified the empty semantic
action catalog, the then-current twelve observation surfaces, current readiness, office questions/course, Core's
already-satisfied 08:00–16:00 schedule with zero input, and unchanged save bytes. The independent
read-only proof produced identical semantic fingerprint
`966e81787748a8ba5eb6f84955f5c85371437110e8c52b95990894cd9017c26b` and save fingerprint
`f04ad31736da01d86b213fedbc904860a1e1c1227e688048180ea679882aeeae` across reconnect.

The same live run moved an overflowed window from a negative-coordinate secondary-display layout
onto the primary display, recognized the open Teams window, and verified a repeated open request
with zero input. A live schedule or role mutation still requires the user to supply the exact desired
value and is not inferred by the test.

## Supported boundary

Evidence is pinned to Software Inc. 1.8.41, Steam build 23094975, Unity 2018.4.36f1, Mono x86_64,
English UI, and the current macOS Steam path. Signed multi-display placement and primary-display
normalization are covered; Windows, other versions, other languages, native ARM64, construction,
furniture relocation, and autonomous office optimization remain unverified.
