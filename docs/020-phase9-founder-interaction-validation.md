# Phase 9 Founder Interaction Validation

Status: implementation and live regression complete; founder ratings pending.

The preserved baseline is
[`evaluation/phase9-interaction-baseline.json`](evaluation/phase9-interaction-baseline.json). It
traces Phase 8 failures through compilation, analyzer selection, finding selection, and response
composition without changing the original Phase 8C results.

Phase 9 corrects intent loss, positive-ranking gaps, vehicle-type aggregation, route negative-count
ranking, subject-insensitive priority review, comparison status, false-premise handling, raw route
identity, redundant explanation invocation, and compact output structure. The focused evaluation
catalog is `tests/fixtures/phase9_interaction_questions.json`.

Founder ratings, exact-question rate, gameplay-use intent, strongest and weakest answers, remaining
gaps, and the Phase 10 gate decision will be recorded only after owner review. No automation
decision has been made.

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
Answers average 41.3 words, the longest is 60 words, and none exceed 60 words. Subjective review
fields remain intentionally blank pending founder ratings.

Live review exposed and closed four additional interaction defects before this artifact was
accepted for rating: vehicle-type labels no longer collapse to the company, “lost the most” is
compiled as lowest profit, company-direction answers no longer overclaim from one interval, and
anomaly comparison evidence is typed consistently. Contextual station and vehicle answers now name
their resolved subject in the first sentence.
