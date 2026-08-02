# ADR-030: Software Inc. Frozen Reference Capability

## Status

Accepted 2026-08-02. Supersedes ADR-020 as product direction without invalidating the capability
and evidence decisions in ADR-021 through ADR-029.

## Context

The Software Inc. milestones established a substantial read-only bridge, visible-control,
approval, durable-workflow, guidance, office, contract, training, and product-development body of
work. They also showed that the game creates a large option and dependency surface before Sim Pilot
can deliver one simple, satisfying player result.

Continuing the numbered Software Inc. roadmap would optimize for integration breadth instead of the
product's shortest useful loop. The completed work should remain reviewable and reusable without
implicitly committing the project to another Software Inc. phase.

## Decision

- Software Inc. is retained as frozen reference capability and is not the current flagship.
- No integration is the current flagship, and no successor game is selected by this decision.
- The complete Software Inc. implementation, tests, documentation, and dated evidence remain in
  the repository.
- The read-only semantic bridge continues to advertise no gameplay actions.
- Existing actions retain their exact compatibility, approval, and evidence gates. Frozen does not
  mean universally live-proven.
- Prompt 8 and other Software Inc. expansion are not authorized by prior roadmap language.
- A future game requires an explicit selection decision, its own adapter, and its own independent
  observation, action, and verification proof.
- The first successor proof must be terminal-first, use one visible gesture per cycle, and verify
  an obvious postcondition before a dashboard or broader roadmap is considered.

## Consequences

Maintenance and regression fixes may preserve the Software Inc. checkpoint. New game-specific
scope requires explicit direction. Generic contracts and safety patterns may be reused, but
Software Inc. mechanics, knowledge, coordinates, bridge fields, and validation evidence may not be
treated as proof for another adapter.

ADR-020 remains in the repository as historical context and is marked superseded. ADR-021 through
ADR-029 continue to describe the exact retained capability and evidence boundaries.
