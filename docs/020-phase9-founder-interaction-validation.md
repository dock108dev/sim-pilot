# Phase 9 Founder Interaction Validation

Status: implementation and offline regression complete; live regression and founder ratings pending.

The preserved baseline is
[`evaluation/phase9-interaction-baseline.json`](evaluation/phase9-interaction-baseline.json). It
traces Phase 8 failures through compilation, analyzer selection, finding selection, and response
composition without changing the original Phase 8C results.

Phase 9 corrects intent loss, positive-ranking gaps, vehicle-type aggregation, route negative-count
ranking, subject-insensitive priority review, comparison status, false-premise handling, raw route
identity, redundant explanation invocation, and compact output structure. The focused evaluation
catalog is `tests/fixtures/phase9_interaction_questions.json`.

Founder ratings, exact-question rate, verbosity rate, gameplay-use intent, strongest and weakest
answers, remaining gaps, and the Phase 10 gate decision will be recorded only after the required
live regression and owner review. No automation decision has been made.

## First live regression

The authorized read-only deterministic regression ran against `phase8a-live-complete.sav`, world
`spb-1636440848-1049736244`, company `Sim Pilot Founder Test`. The bridge load-generation counter
advanced during fresh collections while world, company, capability fingerprint, and server save
path remained stable. Both OpenTTD write flags were disabled.

The nine-path deterministic regression passed in 15.45 seconds after exposing and fixing one
fail-closed defect: an embedded typed-change set queried without its required comparison snapshot
raised evidence validation instead of returning `insufficient_data`. The analyzer now refuses to
emit comparison evidence until the referenced snapshot is actually supplied.

The two authorized Codex invocations both failed closed during compilation. The first returned an
answer intent that differed only at the duplicated provider/deterministic contract boundary. The
second emitted a premise without its conditionally required `premise_check` form and failed schema
validation. No explanation call occurred. Phase 9 now instructs model compilers to return
`answer_intent=null`; the trusted deterministic normalizer derives question forms, premise, metric,
reference, and evidence requirements after validating analyzer, subject, filters, ranking, and
comparison semantics. A further live Codex call requires renewed authorization.
