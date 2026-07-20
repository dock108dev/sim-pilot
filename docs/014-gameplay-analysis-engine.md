# Gameplay Analysis Engine

Phase 8B adds read-only, evidence-backed gameplay questions over the canonical OpenTTD world model.
Analysis requests are not action tasks and never enter the one-action runtime.

## Flow and authority

```text
question -> analysis compiler -> AnalysisRequest -> canonical WorldSnapshot
         -> deterministic analyzer -> findings/evidence/recommendations
         -> deterministic answer composer -> optional explanation provider -> AnalysisResponse
```

Deterministic findings are authoritative. Model providers may compile a question or explain existing
findings, but cannot add evidence, change metrics or severity, claim unsupported causality, or make a
recommendation executable. Invalid explanations are discarded and deterministic output is retained.

Analysis never enters task persistence. Owner-only local JSON session records retain bounded
evidence and compatible conversational context; task lifecycle tables and migrations are unchanged.

## Supported analysis types

The closed version-1 catalog is `company_health`, `financial_summary`, `vehicle_performance`,
`station_performance`, `route_performance`, `service_coverage`, `industry_opportunities`,
`town_coverage`, `fleet_summary`, `world_changes`, `anomaly_detection`, `priority_review`, and
`entity_summary`.

Each request is immutable and semantic: question forms, type, subject IDs, filters, ranking, explicit comparison
snapshot, top-N limit, recommendation preference, and typed answer intent are separate from the
original question. Answer intent preserves concept, metric, period, answer kind, premise,
comparison requirement, conversational reference, and evidence preconditions.
Unknown types, filters, rankings, subjects, analyzers, evidence references, and incompatible
comparisons fail closed.

## Findings, evidence, and recommendations

Findings distinguish observed facts, inferred findings, and data-quality findings. Severity is
informational, opportunity, warning, or critical. Every finding carries one or more compact evidence
references containing a snapshot ID, entity/field identity, observed value, optional comparison
value, and transparent derived-metric inputs.

Confidence describes evidence quality, not model confidence:

- high: a directly observed field from a complete snapshot;
- medium: an inference or derived metric over available evidence;
- low: incomplete or unavailable evidence.

Recommendations are linked to supporting findings, informational, and always
`executable=false`. Priority is deterministic: severity base `0/25/50/75` plus confidence points
`5/15/25`. Stable IDs and entity IDs break ties.

## Answer composition

Phase 9 composes the default answer after deterministic analysis. The composer may select and
phrase retained evidence but cannot create a metric, cause, entity, or recommendation. Compact text
leads with the exact conclusion and shows at most one decisive finding, one recommendation linked
to that finding, one material limitation, and one useful follow-up. It normally remains below 80
words. Detailed and JSON output retain the complete authoritative response.

False loss and zero-debt premises are corrected explicitly. A ranking result is displayed only
when its metric, direction, period, filters, and actual top filtered entity agree. A compatible
comparison pair without evaluated typed delta evidence returns `insufficient_data`. Nearby metrics
are never substituted. Idle no-results name the deterministic depot/stopped/idle criteria.

First-sentence selection is closed and deterministic:

| Analysis type | First-sentence source |
|---|---|
| `company_health` | Requested operating-result concept; explicitly corrects a loss premise. |
| `financial_summary` | Exact requested cash, loan, value, income, or expense finding. |
| `vehicle_performance` | Exact ranked metric and actual top filtered vehicle; idle questions select only idle findings. |
| `station_performance` | Exact requested station metric and top retained station finding. |
| `route_performance` | Exact requested aggregate profit or negative-profit vehicle count. |
| `service_coverage` | Highest-priority retained coverage finding. |
| `industry_opportunities` | Exact ranked opportunity/production finding or highest-priority retained finding. |
| `town_coverage` | Exact ranked population/opportunity finding or highest-priority retained finding. |
| `fleet_summary` | Exact vehicle count or vehicle-type aggregate-profit finding. |
| `world_changes` | Highest-priority typed snapshot-change finding; no typed change evidence is insufficient data. |
| `anomaly_detection` | Highest-priority evaluated typed-delta finding; no evaluated delta is insufficient data. |
| `priority_review` | Highest-priority retained deterministic inspection finding. |
| `entity_summary` | First retained canonical entity finding; an unobserved subject is insufficient data. |

## Sim Pilot heuristics

These are investigation thresholds, not universal OpenTTD truths:

| Signal | Rule | Principal limitation |
|---|---|---|
| Operating result | `income + expenses < 0` | Accounting period may be partial or atypical. |
| Critical cash/debt | cash below zero and loan above zero | Does not predict bankruptcy timing. |
| Low reserve | `cash / max(abs(expenses), 1) < 1` | Expense period and purchases may distort it. |
| Leverage | loan/value at least 0.50 opportunity; at least 1.00 warning | Company value is not liquidation value. |
| Unprofitable fleet | last-year loss share at least 25% warning or 50% critical; minimum four vehicles | New, redirected, or subsidized vehicles may be false positives. |
| Fleet concentration | largest type at least 75%; minimum four vehicles | Concentration is not inherently harmful. |
| Vehicle loss | last-year profit below zero | Current-year loss alone is informational. |
| Old vehicle | age at least 7,305 days | Some vehicle sets do not meaningfully obsolete. |
| Idle vehicle | stopped or depot; warning only with a prior-year loss | Idle state can be intentional. |
| Station service | waiting at least 500 and zero vehicles; warning at 1,000; opportunity at 1,000 with one vehicle | Waiting cargo does not prove congestion. |
| Weak route | aggregate last-year profit below zero | Route is inferred from orders. |
| Route loss share | at least 50%, minimum two vehicles | Correlation is not causality. |

Town opportunity score is:

```text
60 * min(population / 5000, 1)
+ 30 * (1 - min(nearest_company_station_distance / 50, 1))
+ 10 when the observed growth state is growing
```

Industry opportunity score is:

```text
70 * min(total_observed_production / 1000, 1)
+ 30 * (1 - min(nearest_company_station_distance / 50, 1))
```

Only entities without observed selected-company service qualify. Scores expose every input. They do
not evaluate terrain, authority, competitors, cargo consumers, buildability, or future profit.

Material typed changes use both relative and absolute gates: cash `10% and 100,000`, loan increase
`10% and 50,000`, profit zero-crossing `10,000`, and waiting increase `50% and 500`. Entity removal
and coverage regression are warnings; incomplete current collection is a critical data-quality
finding. Currency gates vary with inflation and economy settings.

Bounded anomaly alerts require an explicit comparison: cash drop `25% and 250,000`, vehicle or
route-profit drop `50% and 20,000`, station waiting increase `100% and 1,000`, and route membership
drop `25% and at least two vehicles`. These are fixed change alerts, not learned or statistical
baselines.

## Comparison safety and route identity

Comparisons require distinct complete snapshots with the same world, game, version, capability
fingerprint, chronological order, and observer company. A save/load-generation boundary is allowed
only with a disclosed limitation when world identity remains stable.

Route IDs hash owner, vehicle type, and cyclically normalized orders. Vehicle renaming and snapshot
ordering do not change them. Order changes, vehicle-type changes, and some replacement workflows do;
those changes can appear as route removal/addition. Route comparisons always disclose this limit.

## Providers

The deterministic compiler handles common bounded questions and rejects or clarifies unsupported
ones. Codex CLI and OpenAI compiler/explanation providers are optional and schema-bound. No provider
is selected implicitly. Explanation input contains only the normalized request, top findings,
recommendations, evidence summaries, and limitations; never raw bridge messages, files, history,
credentials, adapters, or executable tools. Prompt input is capped at 64 KB.

## CLI

Analyze a saved canonical snapshot without a model:

```bash
uv run sim-pilot ask --snapshot snapshot.json "Why am I losing money?"
uv run sim-pilot openttd analyze company --snapshot snapshot.json
uv run sim-pilot openttd analyze vehicles --snapshot snapshot.json --top 10
uv run sim-pilot openttd analyze stations --snapshot snapshot.json --detailed
uv run sim-pilot openttd analyze routes --snapshot snapshot.json --json
uv run sim-pilot openttd analyze coverage --snapshot snapshot.json
uv run sim-pilot openttd analyze changes --snapshot current.json --comparison previous.json
```

With neither option, intelligence commands collect a fresh read-only OpenTTD snapshot. `--live`
remains an explicit compatibility flag and `--fresh` documents forced collection intent.
Model use is separately explicit:

```bash
uv run sim-pilot ask --live \
  --compiler-provider codex \
  --explanation-provider codex \
  "Which trains made the least money last year?"
```

Compact answer-first text is the default. `--detailed`, `--json`, `--evidence`, `--top`, `--entity`, `--snapshot`, and
`--comparison` expose detail, stable filters, and explicit snapshot selection. Analysis never
initializes the action runtime.

Phase 8C added owner-only analysis-session records plus `analysis show`, `analysis evidence`, and
`analysis entity`. Phase 8D adds typed presentation metadata for the decisive finding,
recommendation, limitation, follow-up, and evaluated/excluded counts. Detailed output includes all
findings, metrics, evidence, ranking metadata, and snapshot identity.

Phase 9 uses compatible session records to resolve one unambiguous displayed vehicle, station,
route, finding, or top opportunity. It invalidates context across world, save-generation, observer,
or capability changes. Compact output uses entity names and endpoint-based route labels.

The live founder validation proved compiler and explanation faithfulness but did not prove broad
gameplay value. In the bounded company-health founder sample, 40% of answers were correct or
acceptable, 20% revealed at least partially non-obvious information, and 80% were too verbose.
Phase 8D corrected the interaction defects without expanding the analysis catalog or action
surface. The preserved five-question run is documented in
[015-founder-intelligence-validation.md](015-founder-intelligence-validation.md).

## Unsupported evidence and safety

The engine does not claim exact path congestion, construction feasibility, competitor intention,
future profitability, crash causality, or expense causality. The snapshot lacks tile movement,
terrain/buildability, complete competitor state, forecasting evidence, native crash events, and
separate infrastructure/maintenance expenses. The engine adds no gameplay actions, background
monitor, scheduler, HTTP service, UI, or database migration.
