# ADR-009: Intent Compiler and Hosted Provider Boundary

- Status: Accepted
- Date: 2026-07-16

## Context

The runtime accepts a frozen `TaskSpecification`, but users should express bounded objectives in
natural language. Hosted model output is untrusted and may be structurally correct while still
inventing unsupported resources, actions, thresholds, or capabilities. Runtime execution and
decision selection must not become coupled to a hosted provider.

## Decision

Introduce an **Intent Compiler** before task creation. It depends on a `CompilerProvider` protocol
whose only operation converts an instruction into a strict `CompilerResponse`. The compiler then
runs deterministic semantic validation and returns a `CompilerReport` plus a `TaskSpecification`
only when validation status is `valid`.

Use provider-native structured output backed by the Pydantic response model. Never parse prose.
Keep the OpenAI SDK import inside `intent_compiler/providers/openai.py`; runtime, domain,
persistence, and the compiler core remain provider-independent. Keep the scripted runtime decision
provider unchanged.

Version the complete prompt contract as `intent-compiler-v1` and record that version in every
report. Material ambiguity never receives a guessed value. Unsupported intent is reported rather
than converted into an approximate objective. CLI task creation displays the report and requires
confirmation before persisting the validated specification.

Automated tests use a scripted compiler provider and at least twenty golden examples. Hosted tests
run only when explicitly enabled with credentials.

## Consequences

Natural-language variability is isolated before runtime execution. Provider schema compliance does
not replace deterministic business validation. Existing runtime and persistence behavior remains
unchanged, and no compiler report is required in the durable task schema. Prompt changes carry a
versioning and golden-test review obligation.
