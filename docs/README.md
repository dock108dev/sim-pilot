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
- [Software Inc. freeze checkpoint](037-software-inc-freeze-checkpoint.md): frozen capability
  inventory, evidence boundary, and next-game selection gate.
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
- [Rail Route control](023-rail-route-control.md): version-pinned macOS discovery, verified
  pause/resume control, terminal usage, and semantic route-control gate.
- [Game Bridge Protocol v3](024-game-bridge-protocol.md): game-neutral read-only loopback transport,
  authentication, strict identity/sequencing, and snapshots.
- [Rail Route semantic bridge](025-rail-route-semantic-bridge.md): pinned loader, reversible
  installation, typed coverage, observation commands, and validation status.
- [Sim Pilot Test Yard](026-rail-route-test-yard.md): deterministic disposable scenario contract.
- [Software Inc. reference foundation](027-software-inc-foundation.md): adapter registration, exact
  macOS Steam discovery, official lifecycle probe, recovery, and the empty gameplay boundary.
- [Software Inc. read-only semantic bridge](028-software-inc-semantic-bridge.md): authenticated
  main-thread observations, queries, and live non-mutation proof.
- [Software Inc. verified UI control](029-software-inc-verified-ui-control.md): exact-window capture,
  synchronized recognition, bounded gestures, and postcondition verification.
- [Software Inc. teams and hiring](030-software-inc-teams-and-hiring.md): approval-gated team
  creation, paid applicant observation, salary constraints, and recurring-cost verification.
- [Software Inc. guided operator and game knowledge](031-software-inc-guided-operator-and-game-knowledge.md):
  teacher/advisor/operator boundaries, versioned knowledge, crash courses, recommendations, and
  explicit capability-gated delegation.
- [Software Inc. office readiness](032-software-inc-office-readiness.md): schedules, roles, rooms,
  placed equipment, infrastructure, approval boundaries, and current operator limitations.
- [Software Inc. workstation placement](033-software-inc-workstation-placement.md): exact furniture
  catalog planning, itemized approval, visible room assignment/placement, and semantic verification.
- [Software Inc. first contract](034-software-inc-first-contract.md): complete contract observation,
  suitability policy, approval-bound lifecycle control, persistence, and result verification.
- [Software Inc. first training assignment](035-software-inc-first-training-assignment.md): exact
  Education observation, System-design policy, approval, bounded progression, and skill verification.
- [Software Inc. first product Atlas](036-software-inc-first-product-atlas.md): current catalog and
  design observation, conservative runway, approval-bound creation, reviews, and controlled
  Design-to-Alpha-to-Beta progression.
- [Software Inc. freeze checkpoint](037-software-inc-freeze-checkpoint.md): the superseding product
  direction and preserved reference boundary.

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
- [023 — Rail Route terminal control](023-rail-route-control.md)
- [024 — Game Bridge Protocol v3](024-game-bridge-protocol.md)
- [025 — Rail Route semantic bridge](025-rail-route-semantic-bridge.md)
- [026 — Rail Route test yard](026-rail-route-test-yard.md)
- [027 — Software Inc. reference foundation](027-software-inc-foundation.md)
- [028 — Software Inc. read-only semantic bridge](028-software-inc-semantic-bridge.md)
- [029 — Software Inc. verified UI control](029-software-inc-verified-ui-control.md)
- [030 — Software Inc. teams and hiring](030-software-inc-teams-and-hiring.md)
- [031 — Software Inc. guided operator and game knowledge](031-software-inc-guided-operator-and-game-knowledge.md)
- [032 — Software Inc. office readiness](032-software-inc-office-readiness.md)
- [033 — Software Inc. workstation placement](033-software-inc-workstation-placement.md)
- [034 — Software Inc. first contract](034-software-inc-first-contract.md)
- [035 — Software Inc. first training assignment](035-software-inc-first-training-assignment.md)
- [036 — Software Inc. first product Atlas](036-software-inc-first-product-atlas.md)
- [037 — Software Inc. freeze checkpoint](037-software-inc-freeze-checkpoint.md)
- [ADR-019 — Rail Route UI actuation](adr/ADR-019%20Rail%20Route%20UI%20Actuation%20and%20Semantic%20Verification.md)
- [ADR-020 — Software Inc. flagship integration (superseded)](adr/ADR-020%20Software%20Inc%20Flagship%20Integration.md)
- [ADR-021 — Software Inc. read-only semantic bridge](adr/ADR-021%20Software%20Inc%20Read-Only%20Semantic%20Bridge.md)
- [ADR-022 — Software Inc. verified UI control](adr/ADR-022%20Software%20Inc%20Verified%20UI%20Control.md)
- [ADR-023 — Software Inc. teams and hiring](adr/ADR-023%20Software%20Inc%20Teams%20and%20Hiring.md)
- [ADR-024 — Software Inc. guided operator and knowledge authority](adr/ADR-024%20Software%20Inc%20Guided%20Operator%20and%20Knowledge%20Authority.md)
- [ADR-025 — Software Inc. office readiness and infrastructure](adr/ADR-025%20Software%20Inc%20Office%20Readiness%20and%20Infrastructure.md)
- [ADR-026 — Software Inc. visible workstation placement](adr/ADR-026%20Software%20Inc%20Visible%20Workstation%20Placement.md)
- [ADR-027 — Software Inc. first contract workflow](adr/ADR-027%20Software%20Inc%20First%20Contract%20Workflow.md)
- [ADR-028 — Software Inc. first training assignment](adr/ADR-028%20Software%20Inc%20First%20Training%20Assignment.md)
- [ADR-029 — Software Inc. first product Atlas](adr/ADR-029%20Software%20Inc%20First%20Product%20Atlas.md)
- [ADR-030 — Software Inc. frozen reference capability](adr/ADR-030%20Software%20Inc%20Frozen%20Reference%20Capability.md)

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
