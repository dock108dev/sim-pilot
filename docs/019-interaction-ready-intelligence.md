# Phase 9 Interaction-Ready Intelligence

Phase 9 is the read-only product-quality gate between trustworthy analysis and any future bounded
automation. It changes intent preservation, deterministic analysis selection, answer composition,
session-local references, and optional explanation use. It does not add observations, bridge
fields, gameplay writes, planning, forecasting, or action authority.

The requested document numbers `017` and `018` were already occupied by preserved Phase 8
documents, so this design uses the next available number rather than overwriting history.

## Product flow

```text
question
  -> typed question intent and evidence requirements
  -> deterministic analyzer over canonical WorldSnapshot
  -> exact-metric finding and population selection
  -> question-sensitive deterministic answer
  -> optional value-gated explanation
```

Compact output is `Direct answer`, `Evidence`, `Inspect next`, and `Limitation`. Empty sections are
omitted. Lifecycle status, schema details, canonical IDs, and capability internals remain in JSON or
detailed output rather than the default player answer.

## Intent and evidence contract

`AnswerIntent` preserves bounded question forms (`status`, `existence`, `quantity`, `ranking`,
`comparison`, `cause`, `recommendation`, `summary`, `evidence`, `drill_down`, and
`premise_check`), canonical metric, period, premise, comparison need, reference kind, and explicit
evidence requirements. `AnalysisRequest` continues to own subject, IDs, filters, ranking direction
and limit, and comparison identity. Class-level subjects are valid without IDs; entity summaries
require IDs.

Current facts require a current snapshot and the requested field. Comparisons additionally require
a compatible prior snapshot, compatible identity, and typed evidence for the requested metric.
Cause questions require an observed outcome and candidate contributors while remaining explicit
that causality may be unknown. Absent comparison evidence, absent metrics, unresolved subjects, and
incompatible identity produce `insufficient_data` or clarification. A complete evaluated population
with zero matches remains a completed no-result answer.

Canonical metrics are shared across intent, ranking, evidence, findings, and composition. A nearby
metric is never silently substituted. Rankings report eligible, evaluated, and excluded counts,
exclusion reasons, metric, period, direction, and canonical-ID tie-break metadata.

## Premises, selection, and aggregation

Premise questions verify the premise before discussing causes. Company and route loss questions
state directly when the observed result contradicts the premise. Facts, contributors, inferences,
and unknown causes remain distinct.

Positive vehicle rankings evaluate the full filtered population rather than only problem findings.
Vehicle-type profitability aggregates last-year vehicle profit by type. Route loss rankings count
negative-profit vehicles per inferred route. Priority review runs only the named entity class, so a
station question cannot return a vehicle.

## Conversational references and labels

Owner-only analysis sessions retain the prior analysis ID, displayed primary finding and entity,
question, and snapshot. `that vehicle`, `this route`, `that station`, `that finding`, and the top
opportunity resolve only when one compatible current entity is available. World, save generation,
observer company, and capability fingerprint changes invalidate context. Missing, incompatible, or
ambiguous context produces clarification; it never selects a worst or first entity.

Compact labels prefer names. Routes use ordered station endpoints when available, for example
`Route R-004 — Buntborough → Trunton Woods`; the canonical hash remains available in detailed and
JSON output.

## Explanation gate and CLI

The deterministic answer is complete before model use. Quantity, simple ranking, zero-result,
insufficient-data, unsupported, and straightforward answers do not invoke an explanation provider
even when configured. Multi-finding cause, summary, recommendation, or drill-down answers may
invoke it. Validation rejects changed metrics, invented entities, unsupported numbers, missing
critical limitations, and unlinked recommendations. Redundant or overlong prose is discarded.
Responses record `not_invoked`, `improved_answer`, `neutral`, `rejected_by_validator`, or
`provider_failed` for evaluation.

`sim-pilot ask` remains compact by default and supports `--detailed`, `--json`, `--evidence`,
`--fresh`, and `--quiet`. Progress describes snapshot collection and analysis, not provider
internals. Analysis remains separated from action tasks under ADR-014.

## Known limits

Network-wide missing cargo types cannot yet be established from current route-to-cargo coverage and
therefore return insufficient data. Route identity remains inferred from normalized orders.
Waiting cargo does not prove congestion. Infrastructure and maintenance expenses are not exposed
separately. Comparison questions require actual typed change evidence, not merely two files.

