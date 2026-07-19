# Known Limitations

This page describes the current implementation boundary. Dated evaluation reports under `docs/`
are evidence from specific milestones, not the current product contract.

## Operation and deployment

- Sim Pilot is a local, single-process CLI. It has no HTTP API, UI, daemon, scheduler, background
  worker, multi-task dispatcher, remote service, or packaged deployment configuration.
- Durable tasks resume only when an operator invokes `task run` or `task resume`; no process
  automatically scans for pending work.
- SQLite is the only durable backend. The default file is relative to the current checkout unless
  `--database` or `SIM_PILOT_DATABASE` selects another location.
- There is no automatic backup, retention, or database-pruning facility.
- The source checkout is the supported execution surface. A wheel can be built, but this repository
  does not publish packages or images.

## Model-backed behavior

- Natural-language compilation and model-backed decisions require explicitly selecting either the
  OpenAI provider or the separately authenticated Codex CLI provider. There is no automatic
  provider fallback.
- CI and the default test suite use scripted providers and do not prove current external service,
  model, account, pricing, or Codex CLI compatibility.
- Provider recordings and product-evaluation output are opt-in local evidence, not a managed
  telemetry system. They may contain instructions, prompts, and observed state; retention and
  deletion are operator responsibilities.
- Compiler capability catalogs are bounded to the implemented reference and OpenTTD adapters; the
  compiler is not a general planner for arbitrary games or desktop applications.

## Runtime and persistence

- Sim Pilot executes one action per cycle and supports one task invocation at a time. It does not
  coordinate concurrent workers for the same task.
- Process resume uses snapshots and ordered events. It does not promise exactly-once execution
  against external systems; an ambiguous crash window requires adapter-specific or manual
  reconciliation before retry.
- Serialized models are at schema version 1 and the database head is migration `0002`. There is no
  general cross-version data migrator beyond Alembic table migrations and the implemented resume
  compatibility checks.
- Runtime state is durable, but no automatic task export/import or cross-machine transfer workflow
  exists.

## OpenTTD

- The supported live target is OpenTTD 15.3 with Admin protocol 3, bound to loopback. Remote Admin
  Network connections and public multiplayer automation are intentionally rejected.
- Protocol v2 observes companies, towns, industries, selected-company stations and vehicles,
  orders, scoped cargo, and inferred routes. It does not expose a complete tile/terrain or
  infrastructure graph, native events, exact catchments, or pathfinder routes. Captures are
  cooperative rather than atomic and record their start/completion dates.
- The integration's only write
  actions are Admin RCON `set_server_name` and GameScript `set_company_name`, each behind an
  independent opt-in flag.
- Route construction, vehicle/order mutation, schedules, finances beyond the exposed observation,
  UI control,
  memory scraping, and arbitrary console commands are unsupported.
- Live OpenTTD and GameScript tests require a separately configured disposable server and are
  skipped by the normal validation gate.
- Phase 8B analysis is heuristic and read-only. It cannot prove congestion, construction
  feasibility, competitor intent, future profit, crash causality, or infrastructure-expense
  causality. Analysis responses are not durably retained.

## Deferred decisions

The following require product or operational direction rather than a documentation-only fix:

- whether to introduce a long-running worker or multi-task execution model;
- package publication, deployment, backups, and data-retention policy;
- security-scanner ownership and CI failure thresholds;
- remote-service authentication, authorization, encryption, and tenant isolation;
- further OpenTTD observation surfaces or actions beyond the two verified writes;
- a managed retention policy for provider and evaluation recordings.
