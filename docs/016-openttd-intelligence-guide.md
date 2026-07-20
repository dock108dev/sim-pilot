# OpenTTD Intelligence Guide

Sim Pilot can answer bounded, read-only questions about one observed OpenTTD 15.3 company. It does
not build routes, buy vehicles, change orders, predict future profit, or remediate findings.

## Start with direct analysis

With the bridge and Admin password configured, these commands collect a fresh snapshot by default:

```bash
uv run sim-pilot openttd analyze company
uv run sim-pilot openttd analyze vehicles --top 5
uv run sim-pilot openttd analyze stations --top 5
uv run sim-pilot openttd analyze routes --top 5
uv run sim-pilot openttd analyze coverage
```

Use `--snapshot snapshot.json` to analyze a selected canonical snapshot. Use `--fresh` to make the
collection intent explicit. Add `--quiet` for scripts, `--detailed` for full evidence and snapshot
identity, or `--json` for the canonical `AnalysisResponse` only.

## Ask a natural-language question

Deterministic compilation is the default and makes no model call:

```bash
uv run sim-pilot ask "Why am I losing money?"
```

Select local Codex compilation explicitly:

```bash
uv run sim-pilot ask \
  --compiler-provider codex \
  "Which vehicles lost the most money last year?"
```

Optional explanation is separate:

```bash
uv run sim-pilot ask \
  --compiler-provider codex \
  --explanation-provider codex \
  --style compact \
  "Which station should I inspect first?"
```

Provider output never becomes evidence. Deterministic findings remain authoritative, and an
unfaithful explanation is rejected. A faithful explanation is also suppressed when it merely
repeats the deterministic answer. OpenAI is never invoked silently.

The first sentence answers the requested concept directly. For example, a positive company result
corrects “Why am I losing money?” instead of printing a generic health summary. Compact output then
shows at most one observed result, one supported inspection recommendation, one limitation, and one
follow-up.

## Evidence and entities

Every successful text answer prints an analysis ID. Use it to inspect the saved local session:

```bash
uv run sim-pilot analysis show analysis:0123456789abcdefabcd
uv run sim-pilot analysis evidence analysis:0123456789abcdefabcd FINDING_ID
uv run sim-pilot analysis entity analysis:0123456789abcdefabcd vehicle V-001
```

Snapshot-local aliases such as `V-001`, `S-001`, and `R-001` are readable handles. Canonical IDs
remain authoritative. Direct entity commands are also available:

```bash
uv run sim-pilot openttd vehicle V-001 --snapshot snapshot.json
uv run sim-pilot openttd station S-001 --snapshot snapshot.json
uv run sim-pilot openttd route R-001 --snapshot snapshot.json
```

## Snapshots and comparisons

Complete snapshots can be cached for at most 30 seconds only when world ID, save generation, and
capability fingerprint are independently verified. Reuse fails closed when identity cannot be
verified. Cached state must be disclosed; there is no background process.

Comparison requests require complete compatible snapshots:

```bash
uv run sim-pilot openttd analyze changes \
  --snapshot current.json \
  --comparison previous.json
```

A compatible pair alone does not guarantee useful history: the current snapshot must contain or
derive typed changes. Treat a zero-change answer as meaningful only when actual delta evidence was
evaluated. Otherwise Sim Pilot returns `insufficient_data` and asks for a compatible snapshot with
typed changes.

## What works best

Current strongest questions ask for directly observed rankings or facts:

- cash and loan values;
- losing vehicles by an explicit profit period;
- station waiting cargo;
- inferred-route aggregate vehicle profit;
- unserved observed industries and towns;
- evidence behind an existing finding.

Broad questions such as “What should I do?” require clarification. Crash causality, ten-year
forecasts, construction, exact congestion, and prescriptive automation are unsupported.

## Important limitations

- Routes are inferred from normalized vehicle orders and need readable station context.
- Nearby stations do not prove meaningful service.
- Waiting cargo does not prove congestion or insufficient capacity.
- Infrastructure maintenance and detailed expense causality are unavailable.
- Competitor state, tiles, terrain, infrastructure ownership, and native crash events are partial
  or unavailable.
- “Available cash” is the observed balance; committed costs and infrastructure liabilities are not
  exposed.
- Model explanations add latency and are hidden when they do not materially improve the answer.

See [Founder Intelligence Validation](015-founder-intelligence-validation.md) for measured product
results and [Gameplay Analysis Engine](014-gameplay-analysis-engine.md) for deterministic rules.
