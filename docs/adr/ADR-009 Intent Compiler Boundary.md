# ADR-009: Intent Compiler and Hosted Provider Boundary

- Status: Accepted — amended 2026-07-19
- Date: 2026-07-16

## Context

The runtime accepts a frozen `TaskSpecification`, but users should express bounded objectives in
natural language. Hosted model output is untrusted and may be structurally correct while still
inventing unsupported resources, actions, thresholds, or capabilities. Runtime execution and
decision selection must not become coupled to a hosted provider.

## Decision

Introduce an **Intent Compiler** before task creation. It depends on a `CompilerProvider` protocol
whose only operation converts an instruction into a strict `CompilerProviderResult`. That result
contains the untrusted `CompilerResponse` and a separate provider-metadata envelope for provider
name, optional model, and optional token usage. The compiler then runs deterministic semantic
validation and returns a `CompilerReport` plus a `TaskSpecification` only when validation status is
`valid`.

Use provider-native structured output backed by the Pydantic response model. Never parse prose.
Keep the OpenAI SDK import inside `intent_compiler/providers/openai.py`; runtime, domain,
persistence, and the compiler core remain provider-independent. Keep the scripted runtime decision
provider unchanged.

The initial complete prompt contract was `intent-compiler-v1`. Task 6C advances it to
`intent-compiler-v2` and supplies an explicit environment capability catalog, keeping OpenTTD
resources and actions out of the global reference-simulation prompt. Record the selected prompt
version in every report. Material ambiguity never receives a guessed value. Unsupported intent is reported rather
than converted into an approximate objective. CLI task creation displays the report and requires
confirmation before persisting the validated specification.

The selected capability catalog stamps `TaskSpecification.adapter_type`; this is composition
metadata supplied by the caller, not a provider guess. It persists with the specification so
restart selects the same adapter even when resources such as `cash` exist in multiple environments.

Automated tests use a scripted compiler provider and at least twenty golden examples. Hosted tests
run only when explicitly enabled with credentials.

Default CLI composition uses `NoProviderConfigured`; hosted compilation requires explicit
`--provider openai` selection and independently supported OpenAI API credentials. Sim Pilot does
not read or reuse Codex CLI or ChatGPT session authentication. A `RecordingCompilerProvider` may
wrap a configured provider only when the caller supplies a recording directory. It atomically
writes versioned JSON containing the instruction, prompt, prompt version, structured response,
latency, provider metadata, model, and token usage when available. Recording is disabled by default
because instructions may be sensitive.

## Consequences

Natural-language variability is isolated before runtime execution. Provider schema compliance does
not replace deterministic business validation. Existing runtime and persistence behavior remains
unchanged, and no compiler report is required in the durable task schema. Prompt changes carry a
versioning and golden-test review obligation.

Provider telemetry remains outside `TaskSpecification` and durable runtime persistence. Offline
development and CI fail clearly instead of silently initiating hosted requests. Recording adds
local diagnostic artifacts only when explicitly requested.

## Amendment: Codex CLI local provider

Task 7.5P adds `CodexCLICompilerProvider` as a second explicit hosted surface for local development
and product evaluation. The OpenAI API provider remains supported. Selecting `--provider codex`
reuses the authenticated local Codex CLI session; it neither reads `OPENAI_API_KEY` nor falls back
to the OpenAI provider. This is not offline inference: `codex exec` contacts the Codex service and
consumes the signed-in account's applicable allowance or credits without Sim Pilot issuing a
direct API-key-billed request.

The Codex implementation uses the same canonical compiler schema and deterministic semantic
validation. A shared subprocess client first performs a non-model capability/authentication probe,
then invokes Codex explicitly in an empty temporary directory with ephemeral mode, JSONL output,
read-only sandboxing, disabled approval, ignored user configuration and project rules, and a
schema-bound final output. Provider selection still defaults to `none`; scripted tests remain the
CI path. The Codex surface is development-only pending separate production suitability and live
compatibility evaluation.
