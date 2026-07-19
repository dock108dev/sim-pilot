# Live Model Evaluation

**Status:** Baseline complete; deterministic corrections applied after review  
**Evaluation date:** 2026-07-19  
**Review date:** 2026-07-19

## Environment

The evaluation ran locally on macOS through the authenticated Codex CLI surface. Sim Pilot did not
read an API key and did not use the OpenAI API provider. Compiler and decision calls used
`gpt-5.6-sol` through Codex CLI 0.144.6. The fixture contained 31 player-language cases and its
SHA-256 was `07d6b88237afafcbd4c07d5b8c1f5426ca8bf8ecd72ed217e2b72d2eebb1f081`.

The run used 31 compiler calls and at most eight runtime iterations per eligible reference case.
Private case records, prompts, responses, and telemetry remain under `data/product-evaluation/`
with owner-only permissions and are excluded from Git.

## Quantitative baseline

| Measure | Result |
|---|---:|
| Cases completed | 31 / 31 |
| Provider calls | 40 |
| Compiler calls | 31 |
| Decision calls | 9 |
| Valid / clarification / unsupported / invalid | 15 / 4 / 10 / 2 |
| Expected-status match | 83.9% |
| Correct clarification rate | 60.0% |
| False clarification rate | 3.8% |
| Unsupported classification accuracy | 100% |
| Runtime attempts | 6 |
| Reported runtime completion | 50.0% |
| Intervention rate | 33.3% |
| Action-rejection rate | 0% |
| Validation-intervention rate | 0% |
| Mean call latency | 7.69 s |
| Median call latency | 7.29 s |
| p95 call latency | 11.93 s |
| Input tokens | 564,250 |
| Output tokens | 8,215 |

There was no direct API-key-billed cost. The calls consumed the authenticated account's Codex plan
allowance or credits, which Sim Pilot cannot price. No provider failures occurred.

## Human review

The owner review found no unsafe cases. With ratings separated by subsystem, the compiler was
judged correct in 24 cases, acceptable in four, and incorrect in three. Decision quality had too
little evidence for a general score; the immediate loan choice in `clear-001` was specifically
annoying despite a correct compilation. Of the six runtime exercises, three exposed incorrect
completion semantics.

The overall suggested distribution is 20 correct, four acceptable, one annoying, six incorrect,
and zero unsafe. The cases requiring explanation are:

| Case | Rating | Finding |
|---|---|---|
| `clear-001` | Annoying decision | Borrowing immediately is permitted but is a surprising default strategy for a cash target. |
| `ambiguous-004` | Acceptable | Safely refused a non-measurable objective; clarification would be more helpful than unsupported. |
| `contradictory-001` | Acceptable | Correctly refused conflicting multi-objective intent; expected taxonomy was too narrow. |
| `contradictory-003` | Acceptable | Correctly found a contradiction plus an unsupported maximum-cash constraint. |
| `openttd-005` | Acceptable | Correct today, but shows the need for a direct read/query product surface. |
| `clear-003` | Incorrect runtime | A housing project was reported complete although none started. |
| `clear-005` | Incorrect runtime | A satisfied run-until objective was classified as blocked by its duplicate stop condition. |
| `clear-006` | Incorrect runtime | A power project was reported complete although none started. |
| `informal-003` | Incorrect compiler | The model emitted 90 for a resource whose valid scale is 0, 0.5, or 1 instead of clarifying. |
| `contradictory-002` | Incorrect compiler | The requested loan method was discarded while its prohibition was retained, producing a falsely valid task. |
| `openttd-006` | Incorrect compiler | The model added an unsupported direction parameter to `reach_resource`. |

## Findings

Clear and informal requests generally compiled faithfully. Ambiguous requests usually produced a
safe clarification rather than invented thresholds. Unsupported requests and the OpenTTD
capability boundary were strong. Contradictions were usually explained correctly, but their
machine status varied between clarification, unsupported, and valid.

The most important baseline failures were deterministic, not model failures. `complete_project`
treated the absence of an active project as proof of completion, and stop conditions were evaluated
before an identical success objective. Those defects inflated the reported completion rate: the
three zero-action completions were not all genuine task successes.

The structured gates prevented malformed specifications from reaching the runtime and no action
bypassed policy or adapter validation. However, the baseline had no rejected runtime action, so it
does not yet provide meaningful live evidence about recovery from bad decisions.

## Corrections after the frozen baseline

The baseline artifacts were not rewritten or rerun. After owner review:

- `complete_project` now requires durable observation evidence that the requested project was
  active during this task before its later absence means completion;
- a satisfied objective takes precedence over a duplicate stop expression, so an already-satisfied
  run-until task completes without a model call;
- evaluation review records now separate compiler, decision, runtime, and overall ratings;
- Intent Compiler prompt `intent-compiler-v3` preserves required-action methods so deterministic
  validation can reject required/forbidden conflicts;
- percentage-like maintenance language requests clarification;
- the OpenTTD prompt uses valid numeric-objective shapes and explicitly permits passive monitoring
  of advertised observations.

These are post-baseline corrections. Their impact on live-model rates remains unmeasured until a
separately authorized regression run.

## Recommended product changes

1. Distinguish cash balance from financial health or add a conservative default financial policy;
   otherwise a cash target can encourage debt maximization.
2. Add a direct observation/query workflow for questions such as company status instead of forcing
   every useful read into a durable task.
3. Keep compiler, decision, runtime, and overall ratings separate in all future evaluations.
4. Reduce static compiler context toward 3,000–5,000 input tokens and decision context toward
   5,000 where possible. Keep static prefixes byte-identical and summarize event history more
   aggressively.
5. Normalize user-facing status explanations for ambiguity, contradiction, unsupported capability,
   and malformed provider output.

## Usability conclusion

Hosted compilation is credible for deliberate task setup, but hosted decision execution does not
yet feel suitable for interactive gameplay. Five-to-fifteen-second compiler calls and roughly
seven-to-twelve-second decision calls are acceptable for evaluation and slow delegation, not for
rapid player interaction. The correct decision is **revise**, not go or stop: preserve the strong
safety boundary, validate the deterministic corrections, then address interaction latency and the
missing read/query surface before treating the product as natural to use.

