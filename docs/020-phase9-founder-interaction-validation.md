# Phase 9 Founder Interaction Validation

Status: Phase 9 complete; Phase 9.1 deterministic and live objective gates passed; Phase 9.1
gameplay-usefulness judgment and the Phase 10 automation gate remain pending owner confirmation.

The preserved baseline is
[`evaluation/phase9-interaction-baseline.json`](evaluation/phase9-interaction-baseline.json). It
traces Phase 8 failures through compilation, analyzer selection, finding selection, and response
composition without changing the original Phase 8C results.

Phase 9 corrects intent loss, positive-ranking gaps, vehicle-type aggregation, route negative-count
ranking, subject-insensitive priority review, comparison status, false-premise handling, raw route
identity, redundant explanation invocation, and compact output structure. The focused evaluation
catalog is `tests/fixtures/phase9_interaction_questions.json`.

The founder rating is preserved in
[`evaluation/phase9-founder-rating.json`](evaluation/phase9-founder-rating.json). It applies to the
five-case representative subset selected from the 24-question run rather than five independently
submitted ratings.

## First live regression

The authorized read-only deterministic regression ran against `phase8a-live-complete.sav`, world
`spb-1636440848-1049736244`, company `Sim Pilot Founder Test`. The bridge load-generation counter
advanced during fresh collections while world, company, capability fingerprint, and server save
path remained stable. Both OpenTTD write flags were disabled.

The nine-path deterministic regression passed in 15.45 seconds after exposing and fixing one
fail-closed defect: an embedded typed-change set queried without its required comparison snapshot
raised evidence validation instead of returning `insufficient_data`. The analyzer now refuses to
emit comparison evidence until the referenced snapshot is actually supplied.

The first two authorized Codex invocations failed closed during compilation. The first returned an
answer intent that differed only at the duplicated provider/deterministic contract boundary. The
second emitted a premise without its conditionally required `premise_check` form and failed schema
validation. Phase 9 now instructs model compilers to return `answer_intent=null`; the trusted
deterministic normalizer derives question forms, premise, metric, reference, and evidence
requirements after validating analyzer, subject, filters, ranking, and comparison semantics.

After that correction, the live Codex compiler check passed in 13.68 seconds and the independent
value-gated explanation check passed in 28.91 seconds. Both remained read-only. The explanation
path was invoked only for the deliberately eligible station finding.

## Focused founder review

The final read-only review is
`data/founder-intelligence/20260720T015816Z-phase9-review/manual-review.json`; its manifest pins
world `spb-1636440848-1049736244`, company `Sim Pilot Founder Test`, comparison snapshot
`spb-1636440848-1049736244:world:91048`, and current snapshot
`spb-1636440848-1049736244:world:93053`. Both write flags were disabled and the generator made zero
model invocations.

The set contains 24 questions, including rephrasings, valid and missing comparisons, unsupported
forecasting, false premises, rankings, and three contextual follow-ups. Objective results are 3
`completed`, 18 `completed_with_limitations`, 2 honest `insufficient_data`, and 1 `unsupported`.
Answers average 41.3 words, the longest is 60 words, and none exceed 60 words. Per-case subjective
fields in the full review remain blank because the owner chose one aggregate rating for the bounded
five-case subset.

Live review exposed and closed four additional interaction defects before this artifact was
accepted for rating: vehicle-type labels no longer collapse to the company, “lost the most” is
compiled as lowest profit, company-direction answers no longer overclaim from one interval, and
anomaly comparison evidence is typed consistently. Contextual station and vehicle answers now name
their resolved subject in the first sentence.

## Founder rating and success targets

The representative subset received `correct`, `answered_exact_question=yes`, `too_verbose=no`,
`would_use_during_gameplay=yes`, and no unsafe signal. The owner explicitly concluded that Phase 9
passes the interaction-quality gate. This satisfies the subjective correctness, exact-question,
verbosity, safety, and gameplay-use targets for the reviewed subset. It is an aggregate founder
judgment, not a statistically independent per-case rate across all 24 results.

The deterministic review and regression suite separately confirmed that all missing-comparison
cases return `insufficient_data`, false premises are corrected, named subjects remain preserved,
and rankings use the requested metric and direction.

The strongest answers identify a specific vehicle, station, or route immediately and attach the
decisive evidence. The weakest remaining surface is `Inspect next`: some lines are generic,
mechanical, repeat the finding, or use internal route and vehicle phrasing. Some simple factual
answers also retain technically correct but low-value limitations, especially the zero-debt case.
These are interaction polish issues, not P0 correctness or safety defects.

## Phase 10 automation gate

Phase 9 is complete, but bounded gameplay automation should remain **on hold**. The owner rated
recommendations only `partially` useful, so the requirement for one consistently useful advisory
recommendation whose execution would save meaningful effort is not yet demonstrated.

The best product candidate is **inspect or highlight the named entity from the decisive finding**.
It follows the strongest observed value, has clear intent, is bounded, and avoids economic game
mutation. It is not currently a production capability: the OpenTTD bridge advertises only
`set_company_name`, not client navigation or highlighting. `set_company_name` is not a recurring
gameplay-value candidate and should not be promoted merely because it is available. No Phase 10
implementation or prompt is authorized by this report.

## Phase 9.1 recommendation-usefulness continuation

Phase 9.1 replaces compact recommendation prose and generic follow-ups with the typed,
deterministic `InspectionGuidance` contract described in
[`019-interaction-ready-intelligence.md`](019-interaction-ready-intelligence.md). The focused
quality catalog is `tests/fixtures/phase9_1_recommendation_quality.json`; it covers losing vehicles,
weak vehicle types, worst routes, high-waiting stations, idle vehicles, observed industry
opportunities, missing cargo coverage, healthy companies, insufficient evidence, and
false-premise correction. Contract and catalog tests reject repeated findings, generic guidance,
unsupported causal certainty, wrong entities, and over-budget guidance.

The fresh final read-only review is
`data/founder-intelligence/20260720T204539Z-phase9-review/manual-review.json`; its manifest pins
world `spb-1636440848-1049736244`, company `Sim Pilot Founder Test`, comparison snapshot
`spb-1636440848-1049736244:world:120445`, and current snapshot
`spb-1636440848-1049736244:world:122501`. Both write flags were disabled and the run made zero
model invocations. All 23 supported answers rendered a specific evidence-linked inspection or an
explicit reason that no responsible next inspection was available. The 24-answer set averaged
58.0 words, had a 77-word maximum, and had no answer over the 80-word interaction budget.

The strengthened live regression separately passed against a fresh snapshot pair and asserted the
typed guidance linkage for the six-question live set, missing and valid comparisons, and a
contextual vehicle follow-up. Factual correctness, false-premise correction, contextual references,
and the read-only boundary remained intact.

The objective implementation and live-evidence gates pass. The subjective acceptance condition—an
owner judgment that at least one recurring recommendation is consistently useful during actual
gameplay—has not yet been recorded. The evidence is preserved for that review, and gameplay
automation remains on hold until the owner records that judgment.
