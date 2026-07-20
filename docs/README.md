# Sim Pilot Documentation

Start with the root [README](../README.md), then use the guide that matches the work being done.

## Engineer guides

- [Development and architecture](development.md): setup, validation, package boundaries, tests,
  and maintenance conventions.
- [Environment and configuration](configuration.md): configuration precedence, every supported
  environment variable, defaults, credentials, and opt-in test gates.
- [Data and persistence model](data-models.md): public models, durable records, SQLite tables,
  migrations, transactions, and compatibility rules.
- [Operations and CLI](operations.md): databases, providers, durable tasks, OpenTTD, recovery,
  diagnostics, and evaluation runs.
- [Known limitations](known-limitations.md): current product boundary and unsupported behavior.
- [Security hardening](014-security-hardening-review.md): trust boundaries, implemented controls,
  and remaining security roadmap.
- [Failure handling](015-abend-handling.md): failure classification, durable outcomes, and operator
  response.
- [SSOT enforcement](016-ssot-enforcement.md): authoritative modules and retained compatibility
  boundaries.
- [Gameplay analysis engine](014-gameplay-analysis-engine.md): read-only questions, deterministic
  findings, heuristics, evidence, optional explanations, and CLI usage.
- [OpenTTD intelligence guide](016-openttd-intelligence-guide.md): player-facing questions,
  commands, evidence drill-down, freshness, comparisons, and limitations.
- [Phase 9 interaction-ready intelligence](019-interaction-ready-intelligence.md): question forms,
  compact composition, session references, and explanation gating.
- [Phase 9 founder validation](020-phase9-founder-interaction-validation.md): completed interaction
  gate and the remaining Phase 9.1 gameplay-usefulness judgment.
- [Phase 9.2 low-latency intelligence](021-phase9.2-low-latency-intelligence.md): measured
  collection cost, bounded caching, identity verification, and freshness policy.
- [Phase 10A named-entity inspection](022-phase10a-named-entity-inspection.md): live capability
  discovery and the current explicit `unsupported` boundary.

## Product and implementation contracts

- [000 — Vision](000-vision.md)
- [001 — Runtime design](001-month-1-design.md)
- [002 — Reference simulation](002-reference-simulation.md)
- [003 — OpenTTD integration](003-openttd-integration.md)
- [004 — GameScript capability discovery](004-openttd-gamescript-capability.md)
- [005 — GameScript bridge protocol](005-openttd-bridge-protocol.md)
- [013 — OpenTTD world observation](013-openttd-world-observation.md)
- [014 — Gameplay analysis engine](014-gameplay-analysis-engine.md)
- [018 — Answer-first product interaction](018-answer-first-product-interaction.md)

The RFCs define public behavior. The implementation guides describe how to work with the current
tree. When they disagree, update the guide or stop and resolve the contract conflict before changing
runtime behavior.

## Architecture decisions

Accepted Architecture Decision Records are under [`docs/adr`](adr/), covering Python, uv,
Pydantic, SQLite, simulation boundaries, event storage, persistence, recovery, compiler and
decision providers, OpenTTD, GameScript, and Codex CLI isolation.

## Evaluation and milestone evidence

These files are retained as dated evidence rather than current operating instructions:

- [007 — Live model evaluation](007-live-model-evaluation.md)
- [008 — Founder usage checklist](008-founder-usage-checklist.md)
- [009 — Product usability findings](009-product-usability-findings.md)
- [012 — Phase 7.6 stability report](012-phase-7.6-stability-report.md)
- [017 — Phase 8B live founder evaluation](017-phase-8b-live-evaluation.md)
- [Phase 8C — Founder intelligence validation](015-founder-intelligence-validation.md)

Use [operations.md](operations.md) for current commands.
