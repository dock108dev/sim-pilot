# Product Usability Findings

**Status:** Founder stability fixes complete
**Date:** 2026-07-19  
**Evidence:** `docs/008-founder-usage-checklist.md`

## Outcome

The product is workable as an engineering prototype and demonstrates unusually strong safety,
durability, and verification boundaries. It is not yet a natural player-facing tool. The median
workflow is reliable but verbose. The original founder pass found two failed critical paths;
Phase 7.6 corrected hosted Codex runtime decisions and GameScript company-name crash reconciliation.

The original 37-workflow pass produced a mean usefulness rating of 3.5/5. Configuration,
offline defaults, approvals, cancellation, restart, direct OpenTTD writes, duplicate handling, and
identity mismatch behavior were strong. The affected-workflow rerun now passes hosted execution
and GameScript crash recovery; the original 3.5 score remains historical and was not recomputed.

## Prioritized issues

## Resolved in Phase 7.6

- Codex decision composition now selects `SIM_PILOT_CODEX_MODEL` (`gpt-5.6-sol` by default), not
  the OpenAI decision-model default.
- Prompts travel through stdin instead of an argument plus non-terminal `/dev/null`; the harmless
  additional-input notice no longer appears.
- Nonzero exits report the actual JSONL provider error rather than unrelated stderr, and failed
  commands cannot print metadata from an earlier event.
- Every Codex call and recording carries a unique invocation ID in addition to the request ID.
- Recovery dispatch is explicit by adapter type. The OpenTTD company-name crash path verifies
  bridge identity and fresh state, never invokes reference replay, and never retries blindly.
- The affected founder workflows and live OpenTTD crash scenario pass. Detailed evidence is in
  `docs/012-phase-7.6-stability-report.md`.

### P2 — recurring friction

- Resolved in the SSOT enforcement pass: `SIM_PILOT_DATABASE` now selects the same database for
  application commands and raw Alembic commands; explicit programmatic URLs still take precedence.
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
| Setup | Reproducible; the database URL inconsistency found during this pass is now resolved. |
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

The two founder-blocking execution defects are resolved. Phase 7.7 may begin, but it should remain
a narrow product-value proof rather than an infrastructure expansion. Do not redesign the CLI
first. The next proof should focus on whether existing bridge telemetry can deliver meaningful
planning value, not on adding more administrative controls.
