# Product Usability Findings

**Status:** Founder pass complete  
**Date:** 2026-07-19  
**Evidence:** `docs/008-founder-usage-checklist.md`

## Outcome

The product is workable as an engineering prototype and demonstrates unusually strong safety,
durability, and verification boundaries. It is not yet a natural player-facing tool. The median
workflow is reliable but verbose, and two critical paths failed: hosted runtime decisions through
Codex CLI and crash reconciliation for the GameScript company-name action.

The 37-workflow pass produced a mean usefulness rating of 3.5/5. Configuration,
offline defaults, approvals, cancellation, restart, direct OpenTTD writes, duplicate handling, and
identity mismatch behavior were strong. Hosted execution and GameScript crash recovery were
unusable in their tested forms.

## Prioritized issues

### P0 — blocks use

#### Hosted Codex decision execution fails

`task run --decision-provider codex` failed with:

```text
Codex CLI exited with status 1: Reading additional input from stdin...
```

Compilation through the same authenticated Codex installation succeeds. The decision failure is
therefore specific to the decision invocation/input path, not general authentication. The runtime
failed closed and durably recorded the failure, but the CLI then printed metadata from the most
recent scripted decision, which can mislead an operator into associating stale evidence with the
failed hosted call.

Required correction:

- make decision subprocess input compatible with the installed Codex CLI;
- add a live one-decision regression test for the exact runtime context size/path;
- display decision metadata only when correlated with the current run attempt.

### P1 — materially damages trust

#### GameScript company-name recovery is advertised but not implemented

After an injected crash immediately after a verified `set_company_name` write, fresh observation
confirmed that the company name changed. `inspect_recovery` routed the action to reference-
simulation replay and raised `unsupported reference adapter snapshot`. The bridge advertises
reconciliation, so this mismatch is a trust defect.

Required correction:

- add action-specific `set_company_name` reconciliation;
- compare prior and fresh company name plus bridge/save identity;
- classify definitely executed, definitely not executed, identity mismatch, or ambiguous;
- never resend the command during inspection or resume;
- add durable live and offline regression coverage.

#### Failure output can show stale decision metadata

A hosted provider failure was followed by the previous scripted `decision_generated` event. The
task state was safe, but the output was semantically false for the current invocation.

Required correction: correlate displayed metadata to events appended during the current command,
or omit it when no decision was generated.

### P2 — recurring friction

- `SIM_PILOT_DATABASE` affects application commands but not raw `alembic current`; add an
  application-level current command or a shared URL mechanism.
- Observation, action, and bridge commands emit very large JSON documents. Default to a concise
  operator summary with an explicit `--json` or `--evidence` mode.
- `openttd capabilities` reports safe defaults, while live negotiation lives under doctor/bridge.
  Label configured, default, and negotiated capability views distinctly.
- Events are accurate but hard to scan. Add event-type filters and a compact timeline.
- Recovery resolution terminology is precise but demands architecture knowledge. Recommend safe
  options and explain consequences.
- Stale-state, crash, duplicate, conflict, identity, and save/load exercises lack public disposable
  setup commands, forcing use of test/internal APIs.
- The scripted provider is useful for proof but always advances time for numeric reference tasks;
  it is not an operator-authored script surface.
- Hosted compiler latency needs visible progress feedback.
- Direct observation questions still lack a query-oriented product surface.

### P3 — polish

- End task creation output with a prominent task ID and next command.
- Return the updated task from cancellation.
- Add optional field selection to watch output.
- Surface bridge reconnect count and save-generation changes explicitly.

## Category summary

| Category | Finding |
|---|---|
| Setup | Reproducible; database URL behavior is inconsistent between app and Alembic CLI. |
| Terminology | Mostly precise; recovery language is too implementation-oriented. |
| Output | Correct but routinely too verbose for a player-facing CLI. |
| Latency | Local deterministic actions are fast; hosted compilation is noticeably slow; hosted decisions failed. |
| Model behavior | Compiler was useful; decision usability could not be established in this pass. |
| Task lifecycle | Creation, approval, denial, cancellation, blocking, failure, restart, and resume are durable. |
| Approvals | Reliable and correctly prevent execution. |
| Recovery | Reference recovery is honest; GameScript company-name recovery is broken. |
| OpenTTD integration | Observation and both bounded writes work and verify correctly on the disposable server. |
| Missing gameplay value | Current writes are administrative; the next spike must prove planning or gameplay value. |

## Recommendation

Fix the two P0/P1 execution defects before the gameplay spike, then proceed to spike selection.
Do not redesign the CLI first. The current safety architecture is worth preserving; the next proof
should focus on whether the available bridge telemetry can deliver meaningful planning value, not
on adding more administrative controls.
