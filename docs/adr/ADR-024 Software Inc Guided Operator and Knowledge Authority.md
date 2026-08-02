# ADR-024: Software Inc. Guided Operator and Knowledge Authority

**Status:** Accepted

## Context

An action-only terminal assumes that a player already understands the game well enough to supply a
good objective. Software Inc. needs useful teaching and advice without granting implicit mutation
authority or treating language-model recall as factual evidence.

## Decision

Sim Pilot has three separate roles: Teacher, Advisor, and Operator. Questions, courses, status,
recommendations, and explanations are read-only application services. Only explicit delegation can
reach a UI executor.

Game-neutral strict contracts live in `sim_pilot.guidance`. Versioned game facts and rules remain
inside `sim_pilot.software_inc.guidance`. Checked-in knowledge records provenance and a manual
verification stage. Live observations, calculations, repository knowledge, inference, and missing
information are distinct evidence types; model output is never evidence.

Recommendations are deterministic and bound to snapshot, session, save, capability fingerprint,
and expiration. Delegation requires a current compatible capability marked live-mutation-verified.
The Software Inc. semantic bridge retains an empty gameplay-action catalog, and no generic
persisted-task runtime is implied.

## Consequences

- An unfamiliar player can learn and ask for advice before knowing an objective.
- Merely asking or requesting a recommendation cannot invoke UI input.
- Offline implementation evidence cannot silently become live authority.
- Advice is deliberately incomplete when observations or verified rules are incomplete.
- Direct and interactive CLI commands share the same services.
- Future games can reuse the contracts, but not Software Inc. knowledge or capability proof.
