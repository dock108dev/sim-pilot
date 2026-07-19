# ADR-010: Model-Backed Runtime Decision Boundary

- Status: Accepted — amended 2026-07-19
- Date: 2026-07-16

## Context

The runtime previously requested decisions from a scripted provider using only the current task and
observation. Live execution needs a hosted provider, but provider output remains untrusted and must
not acquire adapter, policy, persistence, approval, or completion authority. Hosted requests also
need bounded context, explicit authentication, observable cost metadata, and an offline-safe default.

## Decision

The runtime depends on `DecisionProvider.decide(DecisionContext) -> DecisionProviderResult`.
`DecisionProviderResult` contains exactly one strict `Decision` and shared `ProviderMetadata`.
`DecisionContext` is a stable, bounded projection containing the task specification, current and
previous observations, exact advertised action schemas, recent relevant event summaries, remaining
authority, restrictions, previous execution, safeguards, and deterministic evaluator progress.
Providers never query repositories or adapters directly.

Use prompt version `decision-provider-v1`. The OpenAI implementation uses Responses API native
Pydantic structured output, disables SDK retries, and performs one explicit retry for configured
transient failures. Authentication, timeout, rate-limit, unavailable, malformed output, semantic
invalidity, excessive context, refusal, empty response, unconfigured provider, and recording failure
cross the boundary as typed errors. Semantic invalidity is not retried.

CLI provider selection defaults to `none`. `--decision-provider openai` is required for hosted
requests; environment variables configure the selected provider but never select it. Codex CLI and
ChatGPT authentication are unrelated to runtime API authentication. The scripted provider remains
available for deterministic execution and CI.

An optional `RecordingDecisionProvider` writes one versioned JSON record before returning the
decision to runtime. Records contain a redacted decision context, structured response, shared
metadata, and validation outcome. Writes are atomic, files use mode `0600`, and recording failure
fails the provider call before adapter execution.

The evaluator retains final completion authority, the policy engine retains authority and
constraint enforcement, and the adapter retains environment validation. Decision metadata is
included in the existing `decision_generated` event payload; prompts are not persisted.

## Consequences

Model selection can vary without changing runtime execution order. Identical runtime inputs produce
stable context serialization, and event history remains bounded before leaving the process. Hosted
failures become durable provider-failure and task-failure events while adapter shutdown behavior is
preserved. Adding or changing advertised action schemas is now an adapter contract change.

## Amendment: Codex CLI local provider

Task 7.5P adds an independently selected `CodexCLIDecisionProvider`. It receives only the same
bounded canonical `DecisionContext`, returns the canonical `Decision`, and remains upstream of all
existing adapter validation, policy, approval, execution, verification, and persistence controls.
It therefore gains no additional runtime authority.

The provider crosses a shared argument-list subprocess boundary in a fresh non-repository
directory. Codex runs ephemerally with user/project rules ignored, read-only sandboxing, approval
disabled, JSONL telemetry, and a strict transport-envelope schema whose JSON payload is validated
as the canonical `Decision`. Metadata records provider surface, CLI
version, model, invocation identifier, latency, prompt version, validation, and reported token
usage. It does not contain authentication data or temporary-directory contents.

`--decision-provider codex` is explicit and separate from compiler selection. It reuses Codex CLI
ChatGPT authentication and applicable plan allowance or credits; it does not require an API key or
use the OpenAI decision provider. Codex subprocess failures are translated to existing decision
errors. The provider does not automatically retry: authentication, usage, compatibility, refusal,
schema, and timeout failures fail closed, while runtime records the established durable failure
events. This provider is development/evaluation infrastructure, not yet a production service
boundary.
