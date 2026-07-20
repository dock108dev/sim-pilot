# Phase 8C Founder Intelligence Validation

- Date: 2026-07-19 to 2026-07-20
- Status: complete; owner confirmed Direction D on 2026-07-20
- Boundary: read-only OpenTTD intelligence; no gameplay mutation
- Save: `phase8a-live-complete.sav`
- World: `spb-1636440848-1049736244`
- Company: `Sim Pilot Founder Test`

## Decision summary

The deterministic engine is trustworthy but the current question-answer experience is not yet a
compelling general gameplay product. The strongest capability is evidence-backed inspection over
large entity collections. The weakest capability is answering the question actually asked:
company-health queries frequently receive the same generic findings even when the player asks
specifically about loss, debt, available cash, or change.

The confirmed primary direction is **Direction D — Improve Product Interaction**. This means
question-sensitive deterministic answers, direct premise correction, fewer repeated sections,
better follow-up context, and honest insufficient-data outcomes. It does not mean adding a GUI or
automation. Route building, purchases, order changes, scheduled monitoring, and autonomous
remediation remain deferred.

## Environment and dataset

The live snapshot was complete and compatible across the selected comparison pair. It contained
one observed company, 22 towns, 81 industries, 199 stations, 435 vehicles, and 101 inferred routes.
The capability fingerprint was
`c7e830e62f9898d01704396f91785c9e4a6e9abf87cc08799f8f49a4d4103ec6`; save generation was
334. Both OpenTTD write flags remained disabled.

The canonical fixture contains 45 natural player questions across company health, vehicles,
stations, routes, towns/industries, changes, drill-down, ambiguity, and unsupported requests.
Thirty-seven are supported or supported with limitations. The live session ran 37 deterministic
cases, 45 Codex compiler cases, and five selected Codex explanations.

## Evaluation method

Pass A ran deterministic analyzers over canonical snapshots. Pass B used Codex only to compile
questions into typed requests; deterministic analyzers remained authoritative. Pass C reused five
Pass B responses and asked Codex only for bounded explanations. Failed baseline evidence was
preserved before affected cases were rerun.

The owner declined a burdensome 37-answer manual form. The subjective founder sample is therefore
the first five company-health cases (`n=5`), combined with full objective measurements. It must not
be presented as a full-catalog subjective rating.

## Objective results

| Measure | Result |
|---|---:|
| Expected compilation outcomes | 45/45 |
| Correct analyzer selections among analyzable requests | 36/36 |
| Faithful model explanations | 5/5 |
| Supported cases meeting every catalog evidence-entity requirement | 14/37 |
| Snapshot latency | 6.99 s and 7.01 s |
| Deterministic analysis median / p95 | 1.58 ms / 5.98 ms |
| Compiler median / p95 | 5.15 s / 7.07 s |
| Explanation median / p95, four recorded calls | 20.63 s / 21.68 s |
| Compact answer median / p95 | 100 / 135 words |
| Compiler tokens | 590,747 total; 376,832 cached input |
| Explanation tokens, four recorded calls | 55,617 total |

The fifth explanation was faithful but its token telemetry was not retained by the CLI session
record. This is a measurement gap, not a zero-token result.

## Founder sample

| Measure (`n=5`) | Result |
|---|---:|
| Correct or acceptable | 40% |
| Incorrect | 60% |
| Revealed non-obvious information, yes or partially | 20% |
| Would use, yes or maybe | 40% |
| Would definitely use | 0% |
| Too verbose | 80% |

The two acceptable answers were trustworthy, but the sample found no strong gameplay-use intent.
The main failure was generic response composition, not fabricated metrics. The engine failed to
correct a contradicted “losing money” premise, omitted the observed zero loan from a debt answer,
and did not make comparison absence decisive in a change question. Model explanation mostly
duplicated deterministic output.

## Strongest and weakest signals

Strongest product signal: deterministic evidence and limitation handling remained trustworthy,
and large-collection inspection can be faster than manual browsing when the question maps directly
to an observed metric.

Weakest product signal: only 40% of the bounded founder sample was acceptable and 80% was too
verbose. Correct compilation is not enough when the selected analyzer produces a generic answer
that misses the requested financial concept.

## Prioritized findings

### P1 — damages trust or blocks normal use

1. Answers are analyzer-shaped rather than question-shaped. Lead with the direct answer, including
   premise correction, before supporting findings.
2. Comparison requests can run against compatible snapshots without usable typed changes. Return
   insufficient data unless an actual comparison delta is available.
3. Ranking metadata can describe the requested metric while displayed findings use another metric
   or the wrong evaluated population.
4. Recommendations can repeat a finding or refer to a lower-ranked retained entity rather than the
   evidence currently shown.

### P2 — recurring friction

1. Compact output remains too long and optional explanations duplicate deterministic content.
2. Inferred route hashes need player-readable station/vehicle labels.
3. Generic partial-coverage limitations do not explain whether the headline metric is reliable.
4. Follow-up suggestions sometimes repeat the original request rather than opening a useful drill-down.

No unsafe result was found. Provider claims that changed metrics, invented entities, or violated
recommendation typing were rejected and fell back to deterministic output.

## Observation and product gaps

| Priority | Gap | Primary type | Product effect | Cost/risk |
|---|---|---|---|---|
| 1 | Question-specific answer plans and premise correction | Product/analyzer | Blocks debt, loss, cash, and change answers despite available facts | Medium |
| 2 | Persisted typed snapshot history and reliable delta construction | Observation/history | Blocks meaningful change, anomaly, growth, and trend answers | Medium; identity-sensitive |
| 3 | Vehicle-type, cargo-type, and negative-route aggregations | Analyzer | Blocks “what is dragging me down?” and missing-cargo questions | Medium |
| 4 | Joined station-route-vehicle evidence and readable route labels | Observation/product | Makes useful station/route findings hard to act on | Medium; bridge-safe |
| 5 | Cargo flow, service frequency, and vehicle capacity | Observation | Prevents capacity or congestion conclusions | High; bridge/performance risk |
| 6 | Expense detail, infrastructure ownership, and tile movement | GameScript limitation | Prevents causal profitability and congestion explanations | High/fundamental |

The first four gaps have future advisory value. None currently justifies gameplay mutation.

## Decision scorecard

| Dimension | Score (1–5) |
|---|---:|
| Answer correctness | 2 |
| Evidence quality | 3 |
| Non-obvious value | 2 |
| Gameplay usefulness | 2 |
| Interaction clarity | 2 |
| Response latency | 3 |
| Observation completeness | 2 |
| Model explanation value | 1 |
| Personal desire to use | 2 |
| Engineering cost to improve | 3 |

## Confirmed direction and tester decision

The owner confirmed **Direction D — Improve Product Interaction**. The highest-value next
capability is a small
question-specific answer layer that selects the decisive metric, corrects false premises, reports
insufficient comparison evidence, and emits one direct answer plus one supporting finding and one
limitation. Deep observation work should follow only for questions that remain valuable after this
interaction correction.

Outside testing is not justified. The bounded sample misses the required 70% correct/acceptable and
40% non-obvious thresholds, and definite gameplay-use intent is below 30%. Additional engineering
help is also not justified yet; the next work is a narrow product/analysis correction, not a
parallel infrastructure program.

The detailed next-phase assignment is
[018 — Answer-first product interaction](018-answer-first-product-interaction.md).
