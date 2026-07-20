# OpenTTD Intelligence Guide

Sim Pilot can answer bounded, read-only questions about one observed OpenTTD 15.3 company. It does
not build routes, buy vehicles, change orders, predict future profit, or remediate findings.

## Start with direct analysis

With the bridge and Admin password configured, these commands use live state. They reuse a
compatible snapshot no more than five seconds old after independently verifying the active bridge
identity; otherwise they collect a complete snapshot:

```bash
uv run sim-pilot openttd analyze company
uv run sim-pilot openttd analyze vehicles --top 5
uv run sim-pilot openttd analyze stations --top 5
uv run sim-pilot openttd analyze routes --top 5
uv run sim-pilot openttd analyze coverage
```

Use `--snapshot snapshot.json` to analyze a selected canonical snapshot. Use `--fresh`, `--live`,
or `--max-snapshot-age 0` to require complete collection. Use `--max-snapshot-age 2` to accept a
verified cache hit no more than two seconds old. Add `--quiet` for scripts, `--detailed` for full
evidence, freshness, and snapshot identity, `--evidence` for primary metric inputs, or `--json` for
the canonical response including freshness metadata.

## Ask a natural-language question

Deterministic compilation is the default and makes no model call:

```bash
uv run sim-pilot ask "Why am I losing money?"
```

Select local Codex compilation explicitly:

```bash
uv run sim-pilot ask \
  --compiler-provider codex \
  "Which vehicles lost the most money last year?"
```

Optional explanation is separate:

```bash
uv run sim-pilot ask \
  --compiler-provider codex \
  --explanation-provider codex \
  --style compact \
  "Which station should I inspect first?"
```

Provider output never becomes evidence. Deterministic findings remain authoritative, and an
unfaithful explanation is rejected. A faithful explanation is also suppressed when it merely
repeats the deterministic answer. Simple quantities, rankings, no-results, and insufficient-data
answers do not invoke the configured explanation provider. OpenAI is never invoked silently.

The first sentence answers the requested concept directly. For example, a positive company result
corrects “Why am I losing money?” instead of printing a generic health summary. Compact output then
shows at most one decisive evidence item, one typed inspection step, and one limitation.

`Inspect next` names the selected vehicle, station, inferred route, industry, town, company, or
vehicle type when the evidence identifies one. It tells the player which in-game observations to
compare and what competing explanations that comparison could distinguish. It does not repeat the
finding or treat waiting cargo, losses, proximity, or an inferred route as proof of a cause. When
the current evidence identifies no responsible target—such as missing route cargo coverage or a
healthy result with no urgent problem—the section says explicitly that no responsible next
inspection can be recommended and why.

Follow-up references such as `that vehicle` or `this route` use only the single primary entity from
the latest compatible local analysis. Ambiguous, missing, or incompatible context asks for
clarification instead of silently choosing an entity.

Analysis sessions are retained as owner-only local files for evidence drill-down and compatible
contextual follow-ups. They are separate from durable action-task persistence and have no managed
retention or pruning policy. Sessions written before Phase 9.1 remain readable for context, but
their old prose is not upgraded into invented inspection guidance; rerun the question to generate
current guidance.

## Evidence and entities

Every successful text answer prints an analysis ID. Use it to inspect the saved local session:

```bash
uv run sim-pilot analysis show analysis:0123456789abcdefabcd
uv run sim-pilot analysis evidence analysis:0123456789abcdefabcd FINDING_ID
uv run sim-pilot analysis entity analysis:0123456789abcdefabcd vehicle V-001
uv run sim-pilot analysis inspect analysis:0123456789abcdefabcd FINDING_ID
```

`analysis inspect` is explicit and never runs from `ask`. On the supported OpenTTD 15.3 dedicated
integration it validates the retained reference against a fresh live snapshot, then returns
`unsupported`: the bridge cannot independently verify that a client opened or focused the named
entity. It does not send a bridge command or mutate economic state.

Snapshot-local aliases such as `V-001`, `S-001`, and `R-001` are readable handles. Compact route
labels include ordered station endpoints when available. Canonical IDs
remain authoritative. Direct entity commands are also available:

```bash
uv run sim-pilot openttd vehicle V-001 --snapshot snapshot.json
uv run sim-pilot openttd station S-001 --snapshot snapshot.json
uv run sim-pilot openttd route R-001 --snapshot snapshot.json
```

## Snapshots and comparisons

The default reusable age is five seconds, with a hard cache ceiling of 30 seconds. Complete
snapshots are reused only when a new correlated bridge probe verifies world ID, observer company,
bridge company context, save generation, and capability fingerprint. Missing, corrupt, partial,
expired, unverified, or incompatible state fails closed. The canonical response discloses age,
source, collection duration and in-game interval, identities, bridge sequences, and synchronization
state. There is no background process.

Comparison requests require complete compatible snapshots:

```bash
uv run sim-pilot openttd analyze changes \
  --snapshot current.json \
  --comparison previous.json
```

A compatible pair alone does not guarantee useful history: the current snapshot must contain or
derive typed changes. Treat a zero-change answer as meaningful only when actual delta evidence was
evaluated. Otherwise Sim Pilot returns `insufficient_data` and asks for a compatible snapshot with
typed changes.

## What works best

Current strongest questions ask for directly observed rankings or facts:

- cash and loan values;
- losing vehicles by an explicit profit period;
- station waiting cargo;
- inferred-route aggregate vehicle profit;
- unserved observed industries and towns;
- evidence behind an existing finding.

Broad questions such as “What should I do?” require clarification. Crash causality, ten-year
forecasts, construction, exact congestion, and prescriptive automation are unsupported.

## Important limitations

- Routes are inferred from normalized vehicle orders and need readable station context.
- Nearby stations do not prove meaningful service.
- Waiting cargo does not prove congestion or insufficient capacity.
- Infrastructure maintenance and detailed expense causality are unavailable.
- Competitor state, tiles, terrain, infrastructure ownership, and native crash events are partial
  or unavailable.
- “Available cash” is the observed balance; committed costs and infrastructure liabilities are not
  exposed.
- Model explanations add latency and are hidden when they do not materially improve the answer.
- Named-entity UI navigation is unsupported because client viewport/window state has no verified
  readable postcondition on the supported dedicated-server integration.

See [Founder Intelligence Validation](015-founder-intelligence-validation.md) for measured product
results and [Gameplay Analysis Engine](014-gameplay-analysis-engine.md) for deterministic rules.
