# ADR-014: Analysis Requests Are Separate from Action Tasks

- Status: Accepted
- Date: 2026-07-19

## Context

`TaskSpecification` and the runtime exist to choose, validate, execute, observe, and verify one
action per cycle. A gameplay question is read-only, may return many findings, and must not imply
authority to mutate a simulation. Encoding a question as a fake action task would mix lifecycle,
approval, persistence, and recovery semantics with observation-only work.

## Decision

Use immutable `AnalysisRequest` and `AnalysisResponse` contracts behind a separate query service.
Analyzers consume canonical `WorldSnapshot` values and cannot access adapters, persistence, the
action runtime, raw bridge payloads, or model providers. Analysis is not persisted in task tables.

Optional compiler and explanation providers are separate from the intent compiler and decision
provider. Deterministic findings remain authoritative; explanation references are validated and an
invalid provider result falls back to deterministic output.

## Consequences

- Asking a question cannot execute or authorize an action.
- The one-action runtime, recovery journal, and database schema remain unchanged.
- Snapshot collection is composed at the CLI/application edge and is either live or selected from a
  canonical file.
- Founder-facing evidence drill-down may retain owner-only local session files. These records do
  not enter task tables, event streams, recovery, approval, or action authority.
- Future execution of advice requires a separate, explicit product and authority decision.
