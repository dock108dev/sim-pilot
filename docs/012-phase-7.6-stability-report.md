# Phase 7.6 Stability Report

**Status:** Complete
**Date:** 2026-07-19
**Scope:** Founder defects only; no gameplay capability added

## Outcome

The two founder-pass failures are corrected. Codex compilation and runtime decisions work through
the authenticated local CLI with isolated per-call state, and OpenTTD company-name crash recovery
dispatches to the OpenTTD reconciler. The affected founder workflows, focused offline suites, live
Codex calls, and live OpenTTD crash/restart scenario pass.

## Codex root causes

Three defects combined into one misleading symptom:

1. CLI composition passed `SIM_PILOT_DECISION_MODEL` (`gpt-5.6`) to the Codex decision provider
   instead of `SIM_PILOT_CODEX_MODEL` (`gpt-5.6-sol`). The former is not supported through this
   machine's ChatGPT-authenticated Codex surface and produced the actual HTTP 400 failure.
2. Sim Pilot supplied the complete prompt as an argument while connecting stdin to `/dev/null`.
   Codex 0.144.6 correctly treated non-terminal stdin as an additional prompt source and printed
   `Reading additional input from stdin...` even on successful calls.
3. Nonzero-exit formatting preferred that harmless stderr notice over the JSONL error event, hiding
   the model-compatibility error. After runtime failure, the CLI searched the complete historical
   event stream and printed the last prior `decision_generated` metadata as if it belonged to the
   failed command.

The initial reproduction used the same deterministic decision context three times. All three calls
succeeded, used separate temporary directories and schema/output files, and produced distinct
thread IDs. Each still printed the additional-input notice, proving the notice was not itself the
failure. A control invocation using `codex exec ... -` with prompt bytes on stdin had empty stderr.
An intentionally unsupported-model rerun then exposed the formerly hidden JSONL 400 error.

## Codex fixes

- Deliver prompt bytes through a bounded stdin pipe and use the explicit `-` prompt marker.
- Select the Codex model setting for Codex decisions and the OpenAI decision setting for OpenAI.
- Prefer parsed JSONL error evidence over informational stderr on nonzero exits.
- Add a unique invocation ID to provider metadata and compiler/decision recordings.
- Keep fresh temporary directories, schemas, output files, parsers, metadata, and recordings for
  every call; no shared mutable response state was introduced.
- Correlate CLI decision metadata to events appended after the current command began.
- In explicit debug mode, write an owner-only diagnostic record containing the sanitized command,
  Codex version, invocation/request IDs, process ID, temporary directory, elapsed time, parser
  state, and termination reason. Prompts and full stderr are excluded.

## Recovery root cause and call graph

The former path was:

```text
restart -> reconstruct task/checkpoint -> inspect_recovery
        -> action-name special case for set_server_name
        -> all other actions use reference replay
        -> set_company_name attempts ReferenceSimulationAdapter.from_snapshot(OpenTTD)
```

The corrected path is:

```text
restart -> reconstruct task/checkpoint -> persisted adapter_type
        -> injected ReconciliationDispatcher
        -> explicitly registered adapter reconciler
        -> fresh-state classification -> operator resolution -> resume verification
```

The generic runtime now knows only the registry contract. Application composition registers the
reference reconciler, canonical `openttd`, and the one legacy fully qualified OpenTTD checkpoint
identifier. Unknown adapters, duplicate registrations, and mismatched fresh snapshot types fail
closed.

The OpenTTD reconciler supports only the already verified `set_server_name` and
`set_company_name` actions. Company-name recovery requires stable GameScript instance identity,
company context, and capability fingerprint. The requested name is definitely executed, the prior
name is definitely not executed, and a third value or identity change is ambiguous. Inspection
never sends a command.

## Regression coverage

- One, two, and ten consecutive compiler calls.
- One, two, and ten consecutive decision calls.
- Unique invocation IDs, request IDs, temporary directories, and recording files.
- Prompt stdin transport, malformed JSONL, empty/missing output, unexpected parser failure,
  timeout, process-start failure, output limits, and successful parser restart.
- JSONL error precedence over the former informational stdin message.
- Current-command decision metadata correlation after a prior successful decision.
- Explicit reference/OpenTTD dispatch, legacy OpenTTD compatibility, unknown adapter, mismatched
  adapter, duplicate registration, and multiple registered adapters.
- Company-name definite-executed, definite-not-executed, ambiguous, and identity-change cases.
- Live GameScript rename, injected crash after execution, restart, reconnect, reconciliation,
  mark-executed, resume-to-completion, and original-name restoration.

## Founder rerun

The affected workflows were rerun against Codex CLI 0.144.6 and the loopback OpenTTD 15.3 server.

| Workflow | Result |
|---|---|
| Compile and create | Passed through `gpt-5.6-sol`. |
| Run and resume | Passed; current metadata showed the correct model and fresh IDs. |
| Three consecutive live decisions | Passed; 4.99-5.67 s after the first post-fix smoke run, all exit 0. |
| Deterministic unsupported-model failure | Passed; actual JSONL 400 shown, no stale metadata. |
| Fresh task after provider failure | Passed, demonstrating clean retry-at-new-invocation behavior. |
| Cancellation | Passed. |
| OpenTTD reconnect and rename | Passed. |
| Crash, restart, recovery, verification, resume | Passed without reference replay or command retry. |
| Restore original company name | Passed. |

The live Codex compiler/decision smoke pair completed in 25.04 seconds. The three live GameScript
tests, including crash recovery, completed in 2.54 seconds. Direct API-key billing was not used;
Codex calls consumed the signed-in account's applicable allowance.

## Validation

The complete local gate passed:

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest                 411 passed, 15 skipped
git diff --check
```

The skipped tests are explicitly gated hosted OpenAI/Codex and live OpenTTD tests. The applicable
Codex and OpenTTD tests were enabled and run separately as described above.

## Remaining risks and friction

- Codex CLI remains a development/evaluation surface whose flags and JSONL may change by release.
- No automatic provider retry exists by design; a fresh invocation is safe, but a durable failed
  task remains terminal.
- OpenTTD checkpoints are observations, not authoritative game rollback.
- The legacy OpenTTD adapter identifier remains registered only for pre-7.6 persisted checkpoints.
- Existing P2/P3 output verbosity, migration-status, capability-labeling, and operator-language
  issues remain as listed in `docs/009-product-usability-findings.md`.

## Recommendation

Phase 7.6 is a stable baseline. Phase 7.7 may begin with a narrow intelligence/product-value proof
using existing observation capabilities. Do not add construction or broaden the OpenTTD action
catalog until a separately scoped capability gate proves it.
