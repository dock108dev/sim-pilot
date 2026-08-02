# Software Inc. Guided Operator and Game Knowledge

**Status:** Implemented; live acceptance pending

## Outcome

Prompt 4.5 changes the terminal experience from an action-only prompt into three explicit roles:

1. **Teacher** answers questions and presents short, verified crash courses.
2. **Advisor** recommends one current-save objective and explains its evidence and tradeoffs.
3. **Operator** hands an explicit objective to only an already live-proven UI action.

The semantic bridge remains read-only. The generic persisted-task runtime is still unavailable for
Software Inc. Phase 4 staffing actions remain offline-tested and are rejected by the Guided
Operator until their separate live mutation gate passes.

## Terminal surface

```bash
uv run sim-pilot software-inc ask "What do teams do?"
uv run sim-pilot software-inc ask "How many employees do I have?" --json
uv run sim-pilot software-inc crash-course
uv run sim-pilot software-inc crash-course teams
uv run sim-pilot software-inc crash-course hiring
uv run sim-pilot software-inc crash-course --testing
uv run sim-pilot software-inc recommend
uv run sim-pilot software-inc capabilities
uv run sim-pilot software-inc play
```

The interactive session supports `/crash_course [topic]`, `/status`, `/recommend`, `/why`,
`/capabilities`, `/operate <objective>`, `/help`, and `/quit`. Plain questions also work. Slash
commands are parsed deterministically and never use a model.

Only `/operate` or one of the small, unambiguous imperative forms enters the delegation path.
Ambiguous text returns a clarification. A question mark or question form wins over action wording.

## Contracts and package boundaries

`sim_pilot.guidance` contains strict, game-neutral Pydantic contracts for interaction classes,
evidence, knowledge claims, capability evidence, questions, courses, recommendations, and
delegation results. It imports no game adapter.

`sim_pilot.software_inc.guidance` owns:

- `knowledge_v1.json`: checked-in Software Inc. claims and provenance;
- `knowledge.py`: strict catalog validation and version/build filtering;
- `state.py`: a narrow projection of the read-only bridge snapshot;
- `capabilities.py`: one unified, fingerprinted evidence view;
- `read_service.py`: questions, courses, status, recommendations, and explanations;
- `router.py`: deterministic slash and plain-language routing;
- `delegation.py`: the only guidance module allowed to call UI execution;
- `service.py`: the shared application facade used by direct and interactive commands.

Read services do not import the UI controller. The delegation service cannot promote an action. It
looks up the action in the current capability view and rejects anything that is not a currently
compatible, live-mutation-verified direct UI capability.

## Evidence model

Every answer and recommendation distinguishes:

- `live_observation` from a specific bridge snapshot;
- `deterministic_calculation`, such as a calculation over complete observed fields;
- `verified_repository_knowledge` with a stable claim and provenance;
- `bounded_inference` when a narrow inference is explicitly supported;
- `unavailable` when the required observation or knowledge does not exist.

Model-generated prose is not an evidence type. This milestone adds no model provider and requires
no network access or paid call.

Knowledge claims record a stable ID, game/version/build scope, topic, claim, prerequisites,
applicability, provenance, verification stage, confidence, last verification, related observation
fields/actions, and limitations. The lifecycle is:

```text
unknown
→ researched
→ fixture_validated
→ experimentally_verified
→ live_regression_proven
```

Promotion is a deliberate repository change supported by new evidence; catalog loading never
promotes a claim automatically.

## Current knowledge and question scope

The initial catalog covers the Software Inc. operating loop, the financial-observation boundary,
teams, observed employee fields, Programmer hiring, the separate applicant-search and recurring
salary approvals, the empty semantic action catalog, Phase 3 direct UI actions, and the pending
Phase 4 live gate.

State-grounded answers cover company name/status, cash, team count/list, employee count/team
membership, recurring observed payroll, whether Support Alpha exists, and the bounded financial
health view. Incomplete finance coverage cannot yield a runway or affordability verdict.
Unsupported questions say that the catalog is insufficient; language-model recall is not used as
a fallback.

## Recommendation rules

Rules are deterministic and ordered:

1. Require a compatible current-save snapshot.
2. If the simulation is running, recommend pausing before management review.
3. Require complete teams and employees for staffing advice.
4. If a team has no observed employees, recommend opening Manage Teams to review it.
5. Otherwise recommend reviewing the current team structure.

The result contains the rule, observed evidence, expected benefit, risk, prerequisites, authority,
execution availability, and material unknowns. A recommendation is bound to the save identity,
game session, source snapshot, capability fingerprint, and a five-minute lifetime. `/why` and
`/operate use your recommended plan` reject an expired or mismatched recommendation.

This is intentionally narrow advice. An empty team does not prove that hiring is wise, and the
bridge does not expose enough finance detail to claim affordability.

## Delegation and safety

Delegation preserves the existing UI control contract: preflight the exact current window and
scene, send at most one frame-bound gesture, re-observe, and verify. Unsupported objectives fail
closed. Phase 4 `create_team`, `observe_applicants`, and `hire_employee` remain visible in the
capability view as `offline_integration_tested`, but the Guided Operator sends no UI input and
creates no approval for them while `live_verified=false`.

Current execution also requires all of the following:

- Software Inc. 1.8.41 and Steam build 23094975;
- a current `software-inc-readonly-v4` semantic snapshot;
- an enabled and loaded bridge;
- byte equality between the installed bridge DLL and the repository artifact;
- the same save/session and capability fingerprint for recommendation delegation.

Historical live proof is retained as evidence but does not override a failed current preflight.

## Testing and evidence stages

The normal suite covers routing, strict catalog validation, current-state projection, read-path
non-mutation by construction, crash-course live/fallback output, evidence kinds, unsupported
questions, deterministic recommendations, incomplete observations, stale identities, direct CLI,
interactive commands, explicit delegation, Phase 4 rejection, architecture direction, and the
absence of paid-provider dependencies.

Opt-in live acceptance is:

```bash
SIM_PILOT_LIVE_SOFTWARE_INC_GUIDANCE=1 \
  uv run pytest -m live tests/software_inc/test_live_guidance.py
```

Use only the paused disposable company. It checks current questions/course/recommendation,
explicit rejection of Phase 4, one verified `open_manage_teams` delegation, and unchanged save
fingerprints. Do not label this milestone live-accepted unless that test actually passes against
the installed repository artifact and current save/session.

## Adding or promoting knowledge

1. Add or revise one claim in `knowledge_v1.json`; never edit a different game's catalog.
2. Record a precise provenance locator and the narrowest supported version/build.
3. List required fields/actions and limitations.
4. Add fixture tests for the claim or rule.
5. Promote only to the evidence stage actually established.
6. For `live_regression_proven`, retain a repeatable live test or named milestone evidence.
7. Re-run Ruff, Pyright, the full pytest suite, and any applicable opt-in live gate.

## Remaining gaps

- No complete runway, scheduled-payment, rent, or project-suitability model exists.
- The knowledge catalog is intentionally small and is not expert strategy coverage.
- Recommendations are not persisted across terminal processes.
- Software Inc. has no generic durable multi-step objective runtime yet.
- Phase 4 mutations are not delegated until their live acceptance is complete.
- Other game versions, Windows, native ARM64, layouts, languages, and display scales are unproven.
