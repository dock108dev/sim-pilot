# Phase 8D — Answer-First Product Interaction

- Engineering status: implemented 2026-07-20
- Founder acceptance: one grouped five-answer review pending
- Boundary: observation, analyzers, runtime, persistence, and actions unchanged

## Engineering assignment

Implement a narrow interaction-quality phase over the completed Phase 8C read-only intelligence
surface. The objective is not to make Sim Pilot know more. It is to make Sim Pilot directly answer
the question the player asked using facts and limitations it already has.

Read `AGENTS.md`, the governing RFCs and ADRs, the Phase 8A observation contract, the Phase 8B
analysis engine, and [Phase 8C Founder Intelligence Validation](015-founder-intelligence-validation.md)
before changing code. When documents conflict, stop and report the conflict.

Phase 8D remains read-only. Do not add observations, bridge fields, analyzers, gameplay actions,
planning, construction, purchases, order changes, monitoring, notifications, an HTTP API, a UI, a
second adapter, forecasting, or outside testing.

## Product outcome

The default answer must:

1. answer the exact question in its first sentence;
2. correct a false premise explicitly;
3. preserve subject, metric, period, ranking, and comparison intent;
4. return `insufficient_data` when required evidence is absent;
5. show at most one decisive finding, one supported recommendation, and one important limitation;
6. omit a model explanation when it adds no material information;
7. leave observation, deterministic analyzer, runtime, persistence, and action behavior unchanged.

The target experience is:

```text
You are not losing money at company level in the observed period.

Observed result
Income plus expenses: £941,840

Inspect next
Check the lowest-profit vehicles if you are investigating local losses.

Limitation
The accounting period may be partial, and infrastructure costs are not separated.
```

Do not print a generic company-health summary before this direct answer.

## Phase 1 — Lock the answer contract

Define a small typed, versioned interaction contract within the existing analysis framework. It
must carry only presentation intent that current request fields cannot express, such as:

- requested concept (`health`, `loss`, `debt`, `cash`, `change`, or existing bounded equivalent);
- requested metric and accounting period when explicit;
- whether the question contains a premise that evidence can confirm or contradict;
- whether comparison evidence is required;
- whether the answer is a ranking, fact, explanation, or entity follow-up.

Prefer extending the existing request/response composition boundary over creating another query
framework. Do not put natural-language generation inside deterministic analyzers. Model output
remains untrusted and must validate through the closed compatibility catalog.

Document how first-sentence answers are selected for every currently supported analysis type.
Where the current analyzer cannot satisfy a requested metric, return `insufficient_data`; do not
substitute a nearby metric.

## Phase 2 — Preserve intent through compilation

Update deterministic, Codex, and OpenAI analysis compilers so normalized presentation intent is
preserved alongside the existing analysis type, filters, ranking, subject, and comparison fields.

Required rules include:

- “Why am I losing money?” preserves a loss premise and company-level scope.
- “Am I carrying too much debt?” selects observed loan/leverage evidence, not generic health.
- “Which trains performed best last year?” preserves `rail`, descending last-year profit, and the
  filtered evaluated population.
- “Which routes have the most losing vehicles?” must not become total vehicle count.
- “This route” without one unambiguous contextual route requires clarification.
- A comparison question carries the exact compatible comparison ID but still requires actual typed
  delta evidence.

Reject semantically incompatible analyzer/filter/ranking combinations before analysis. Keep the
provider context bounded to the compatibility catalog, question, required filters, entity-resolution
summary, and selected comparison identity. Never send the world snapshot to a provider.

## Phase 3 — Deterministic answer composition

Add one deterministic composer after analysis and before terminal rendering. It may select and
phrase existing facts; it may not create evidence, causes, metrics, or recommendations.

Composition order:

1. direct answer;
2. decisive observed metric or finding;
3. one non-executable inspection recommendation supported by that finding;
4. one limitation that materially affects the direct answer;
5. one useful follow-up only when it advances the investigation.

The composer must distinguish:

- **confirmed fact** — directly observed value;
- **finding** — deterministic interpretation of evidence;
- **inference** — uncertain joined signal;
- **insufficient data** — required evidence absent.

Do not render empty sections. Do not repeat the question, analyzer name, answer, finding summary,
recommendation rationale, or model wording in multiple sections.

## Phase 4 — Premise correction and no-result behavior

Implement explicit premise correction from authoritative findings:

- If observed company operating result is positive, “Why am I losing money?” begins by saying the
  company is not losing money at the observed company level. It may then distinguish individual
  losing vehicles.
- If loan is zero, a debt answer begins by saying there is no observed outstanding loan.
- If no vehicle matches the deterministic idle criteria, say “No idle vehicles were detected,” and
  name the criteria in the limitation or evidence view.
- If the question asks what changed but the current snapshot has no typed changes derived from the
  selected comparison, return `insufficient_data`. Never interpret “nothing evaluated” as “nothing
  changed.”

False-premise correction must not overclaim. Scope and period belong in the first sentence.

## Phase 5 — Ranking integrity

Before rendering a ranked answer, verify that displayed findings match:

- requested metric;
- requested direction;
- requested period;
- requested filters and subject;
- evaluated population;
- exclusion count;
- deterministic tie-break.

If no retained finding matches the requested ranking metric, return `insufficient_data`. Do not
display current-year loss under a last-year best-performance heading. Evaluated counts must reflect
the filtered population, not all entities or zero inferred from an unrelated analysis type.

Select a recommendation only when it is supported by the decisive displayed finding. A lower-ranked
or hidden finding must not supply the default recommendation.

## Phase 6 — Comparison integrity

Keep compatibility validation unchanged. Add a separate evidence-presence check:

- the comparison ID must match the supplied snapshot;
- snapshots must be compatible under the existing policy;
- the current input must contain or deterministically derive typed changes from that comparison;
- the requested entity/metric change must be represented by evaluated delta evidence.

When any required condition is absent, return `insufficient_data` with one plain-language reason and
the next step: select or collect a compatible comparison snapshot. Do not add snapshot history or a
background collector in this phase.

## Phase 7 — Explanation value gate

Deterministic output is the complete default answer. An explicitly selected explanation provider
may be shown only when the validated explanation adds one of:

- a clearer prioritization among retained findings;
- a supported connection between the decisive finding and inspection recommendation;
- a materially clearer limitation.

Suppress explanations that merely restate existing sentences, metrics, recommendation rationale,
or limitations. Suppression is a successful deterministic fallback, not an error. Preserve all
existing faithfulness checks and provider telemetry.

Support only `compact`, `coach`, and `technical`; compact remains the default.

## Phase 8 — Output limits

Compact output should normally remain under 80 words and must never show more than:

- one direct answer;
- one decisive finding;
- one recommendation;
- one limitation;
- one follow-up.

Detailed output retains all findings, evidence, confidence, snapshot identity, ranking metadata,
and limitations. JSON remains the canonical structured response and must not contain progress text.
`--quiet`, evidence drill-down, entity aliases, and local analysis sessions remain supported.

## Phase 9 — Focused founder validation

Use the preserved Phase 8C snapshots. Do not recollect live state or call a model until the complete
offline gate passes. Rerun only these five company-health questions:

1. How healthy is my company right now?
2. Why am I losing money?
3. Am I carrying too much debt?
4. How much cash do I actually have available?
5. Is the company improving or getting worse?

Also run provider-free regressions for:

- best trains by last-year profit;
- idle vehicles;
- station inspection priority;
- routes with the most losing vehicles;
- one contextual and one context-free route follow-up;
- every comparison analysis type.

Present the five founder answers together in one compact review, not a 37-item form. Ask for only:

- acceptable or not acceptable;
- would use or would not use;
- one optional note covering the set.

Do not request per-case multi-field ratings.

## Testing

Add or update tests for:

- direct first sentence for every supported analysis type;
- positive-result correction of a loss premise;
- zero-loan debt answer;
- available-cash limitation;
- comparison without typed changes returns `insufficient_data`;
- requested metric/period must match displayed findings;
- filtered evaluated and excluded counts;
- ambiguous follow-up clarification;
- clean idle no-result wording and criteria;
- recommendation supports the displayed finding;
- compact section and word limits;
- detailed output remains complete;
- JSON remains canonical and progress-free;
- redundant explanation suppression;
- valuable explanation retention;
- provider failure and faithfulness fallback;
- no action-runtime initialization;
- no gameplay mutation.

Normal CI remains offline and uses scripted providers. Any Codex check requires a separate explicit
gate and owner authorization.

## Documentation

Update:

- `README.md`;
- `docs/014-gameplay-analysis-engine.md`;
- `docs/015-founder-intelligence-validation.md` with the focused before/after result;
- `docs/016-openttd-intelligence-guide.md`;
- `docs/009-product-usability-findings.md`;
- ADR-014 only if the query/action boundary meaning changes.

Do not rewrite or erase the Phase 8C baseline.

## Acceptance criteria

Phase 8D is complete when:

- all five company-health answers lead with the exact requested conclusion;
- false loss and debt premises are corrected from evidence;
- comparison without evaluated delta evidence is `insufficient_data`;
- ranking metric, period, direction, filters, and counts agree with displayed findings;
- compact answers satisfy the one/one/one shape and normally remain under 80 words;
- redundant explanations are suppressed;
- detailed evidence and canonical JSON remain intact;
- the focused founder set is acceptable as a group and the owner indicates they would use at least
  one answer during gameplay;
- Ruff, Pyright, pytest, lock validation, and diff checks pass;
- observation, analyzer, runtime, persistence, and action behavior remain unchanged;
- no gameplay mutation or background process is added.

If the focused five-answer set is still not voluntarily useful, stop and reconsider OpenTTD as the
first product target rather than expanding the feature surface.

## Validation commands

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
git diff --check
```

## Commit plan

1. `Phase 8D1 - answer intent and deterministic composition contracts`
2. `Phase 8D2 - premise comparison and ranking integrity`
3. `Phase 8D3 - compact output and explanation value gate`
4. `Phase 8D4 - focused founder validation and documentation`

Keep commits independently reviewable. Do not include gameplay mutation, new observation fields, or
unrelated cleanup.
