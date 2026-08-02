# ADR-025: Software Inc. Office Readiness and Infrastructure

- Status: Accepted
- Date: 2026-07-26

The purchase/placement deferral in this decision is resolved by ADR-026; the read-only observation,
readiness, schedule/role, server non-inference, and window-normalization decisions remain current.

## Context

Prompt 5 needs to explain and configure early-company readiness without turning an obsolete guide
into authority or granting a compiled mod gameplay writes. The game exposes public room, furniture,
team, employee, and server state, but UI purchase and placement identity is not yet complete.

The live build also demonstrates that `Furniture.CanAssign` is broader than workstation capacity:
toilets can be assignable. Counting it alone would recommend against a needed desk.

## Decision

Keep the semantic bridge read only and add three complete observation surfaces:

- `offices` for rooms and placed furniture;
- `infrastructure` for server groups;
- `office_ui` for schedules, role management, server windows, and current UI geometry.

Count a workstation only when the public object is assignable, requires a chair, is valid, and is
not blocked. Preserve the exact furniture name and supporting fields so the inference remains
auditable.

Implement whole-hour team schedules and supported employee roles as separate visible-UI actions.
They inherit one gesture per cycle, current-frame targeting, post-input re-observation, and exact
semantic verification. Keep them offline evidence until a user-authorized live mutation proves the
specific installed build.

Normalize unsafe macOS placement before control. Resolve all active CoreGraphics displays in signed
global coordinates; when the existing game window fits the primary display but is partly offscreen
or cross-monitor, move it once through the existing Accessibility authority and verify the same
PID/window. Never resize it silently, click an offscreen/display-gap target, or continue when the
window is larger than the primary display.

Treat office purchases as explicit commitments. A later action must observe an exact catalog item,
quantity, unit price, total price, placement target, remaining cash, and any recurring cost before
asking approval. Recurring cost needs separate authority.

Do not advertise room assignment, desk assignment, furniture placement, or server creation while
their stable UI targets and prices are missing. Do not infer a universal source-control server
requirement from the historical Alpha 10 guide.

## Consequences

- Teacher and Advisor can answer office, schedule, role, equipment, and server questions from the
  current save without sending input.
- Sim Pilot can configure exact schedules and roles through ordinary visible controls once their
  live mutation gate is explicitly promoted.
- Existing capacity is preferred before a purchase, but the runtime does not pretend that every
  assignable object is a desk.
- Some Prompt 5 operator requests remain explicitly unsupported until the observation contract is
  sufficient to execute and verify them safely.
- Multi-monitor placement is no longer treated as a fixed-layout assumption; a verified
  primary-display normalization precedes screenshots and input when needed.
- The bridge action catalog stays empty, preserving the adapter boundary for future games.
