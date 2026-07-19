# ADR-013: Codex CLI Local Provider Boundary

- Status: Accepted
- Date: 2026-07-19

## Context

Local product proving needs real model-backed compilation and decisions without requiring Sim Pilot
to hold an OpenAI API key. The installed Codex CLI can reuse an authenticated ChatGPT session, but
it remains a networked hosted-model surface that consumes the account's Codex allowance or credits.
Running a coding agent as a subprocess also risks inherited instructions, tools, repository access,
unbounded processes, sensitive diagnostics, and untrusted output.

## Decision

Support Codex CLI only when selected explicitly. A shared client below both provider
implementations performs a non-billable `--version`, `exec --help`, and `login status` capability
probe. Required local capabilities are non-interactive execution, model selection, ephemeral mode,
JSONL output, output schema, working-directory selection, ignored user/project rules, and a
read-only sandbox. Missing authentication or capabilities produce typed errors; free-form parsing
and API-key fallback are forbidden.

Each call receives an argument-list invocation in a new owner-only temporary directory outside any
Git repository. The command uses `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, `--json`,
`--sandbox read-only`, `approval_policy="never"`, `--output-schema`, `--output-last-message`, an
explicit model, and that directory as `--cd`. It never uses a shell, `--add-dir`, workspace-write,
or repository context. The subprocess receives a small environment allowlist needed for CLI auth,
locale, and certificates; API token variables are not inherited.

The prompt is delivered through a bounded stdin pipe with the explicit `-` prompt marker; it is
never placed in the argument list. This prevents Codex from interpreting a non-terminal stdin as
an additional prompt source.

Stdout, stderr, and duration are bounded. Because the canonical models contain arbitrary JSON maps
that Codex's strict schema subset cannot express directly, the subprocess returns a strict
single-field envelope containing canonical JSON text. The client requires one terminal completion
and one final agent message, validates both copies of that envelope and requires them to agree, then
validates the enclosed JSON against the canonical Pydantic model. Unknown telemetry events are
noted but cannot become the result. Token fields absent from the CLI remain `None`; Sim Pilot does
not estimate them. No automatic retry occurs at this boundary.

Raw JSONL is not stored by default. `SIM_PILOT_CODEX_RECORD_RAW_EVENTS=1` preserves only an
allowlisted, sanitized subset using owner-only atomic writes and also preserves the otherwise
ephemeral debug directory. Full stderr is never persisted. Normal compiler/decision recording
wrappers retain their existing semantic inputs, structured outputs, validation, and metadata.

Every invocation receives a fresh UUID independent of the Codex thread/request ID. When debug
directory preservation is explicitly enabled, an owner-only diagnostic record contains only the
sanitized command, Codex version, invocation and request IDs, process ID, temporary directory,
elapsed time, parser state, and termination reason. It never contains the prompt or full stderr.

Product evaluation records Codex invocation counts and reported usage/latency. It reports direct API
cost as none and allowance/credit consumption as not directly priced by Sim Pilot. Conservative
compiler, decision, total-call, per-call timeout, runtime-iteration, and wall-clock limits apply.
Normal defaults and CI remain network-free.

## Threat model and controls

| Risk | Control |
|---|---|
| Prompt injection in task or game state | Treat inputs as data, prohibit tools in the prompt, require canonical schemas, and run deterministic post-validation. |
| Inherited AGENTS instructions, project rules, hooks, or user configuration | Empty non-repository working directory plus `--ignore-user-config` and `--ignore-rules`. |
| MCP/tool or shell execution | Ignored user configuration, approval policy `never`, read-only sandbox, no shell invocation, and no added directories. |
| Repository or local-file inspection | Fresh temporary directory outside Git repositories; no checkout, mounts, or repository paths in prompts. |
| Credential or environment exposure | Small environment allowlist, no API-key variables, no credential logging, and no authentication-file inspection. |
| Sensitive stderr or telemetry leakage | Bounded stderr held in memory; raw events off by default and sanitized/owner-only when explicitly enabled. |
| Schema bypass or malicious output | Dual validation and equality checking of the strict transport envelope, canonical Pydantic validation of its JSON payload, then existing semantic validation. |
| Hang, child leakage, or oversized output | Per-call timeout, bounded streams, terminate/kill escalation, and typed process errors. |
| Temporary-file retention | Owner-only files and automatic cleanup; preservation requires an explicit debug flag. |
| Allowance exhaustion or accidental spend | Explicit provider selection, no API-cost claim, typed usage-limit failure, and evaluation call/wall-time limits. |

## Consequences

Developers can exercise the real hosted reasoning surface through their existing Codex login without
placing an API key in Sim Pilot. The compiler and runtime remain provider-independent, and model
output remains untrusted. The boundary is intentionally development-only: local Codex releases may
change JSONL or schema behavior, the CLI still contacts an external service, and the isolation flags
reduce but cannot prove the absence of every future CLI-side behavior. A live one-call compatibility
test therefore requires explicit owner authorization and is never part of CI.
