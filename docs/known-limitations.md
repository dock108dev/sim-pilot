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
- `analysis inspect` can validate a finding's vehicle, station, town, or industry against fresh live
  identity and entity state, but returns `unsupported` without execution. OpenTTD 15.3 can dispatch
  some viewport scroll commands, yet the supported Admin/GameScript boundary cannot read a remote
  client's viewport or prove that the named entity was opened or focused.
- Live OpenTTD and GameScript tests require a separately configured disposable server and are
  skipped by the normal validation gate.
- Routine analysis can reuse an owner-only on-disk snapshot for at most the caller's freshness
  window (five seconds by default and never more than 30 seconds) after a live bridge identity
  probe. This is bounded request-local caching, not background monitoring or a persistent
  collector. A cache miss still incurs the full cooperative world collection interval.
- Gameplay analysis is heuristic and read-only. It cannot prove congestion, construction
  feasibility, competitor intent, future profit, crash causality, or infrastructure-expense
  causality. Owner-only analysis session files retain responses and snapshots for evidence
  drill-down and compatible contextual follow-ups, but they are separate from durable action-task
  persistence and have no automatic retention, pruning, backup, or cross-machine transfer policy.
  Pre-Phase-9.1 sessions remain context-readable but require a rerun for typed inspection guidance.

## Rail Route

- The supported target is the Steam macOS build of Rail Route 2.3.24 in fullscreen-window mode.
  Version changes fail closed until the screen contract is revalidated.
- Screen control verifies `pause` and `resume`; `status` is read-only. Protocol v3 keeps the
  semantic bridge read-only. A separate UI catalog adds one `set_route_ui` objective for the
  canonical Test Yard. Natural language is parsed deterministically and does not invoke a model.
- Observation recognizes the selected pause, normal-speed, or accelerated-speed control from a
  fresh screenshot. A menu, loading screen, disabled tutorial control, changed layout, unavailable
  screen recording, or ambiguous recognition fails before input or fails verification without an
  automatic retry.
- The screen-control adapter activates Rail Route and sends its Space binding through macOS
  Accessibility; it does not inject code or modify the game. The separately installed BepInEx
  semantic bridge is opt-in, version/hash pinned, loopback-only, authenticated, and capability
  gated.
- The semantic bridge and loader are live-validated on the pinned macOS x86_64/Rosetta path.
  Pause/speed, play mode, map/save identity, trains, stations, platforms, signals, and switches are
  promoted from populated Prague evidence. Active signal routes had a complete but empty
  collection. Upcoming timetable traffic and `track_occupancy` are live-proven against the Prague
  UI, including exact Com1011/Com1012 times and platform plus allocated/occupied track state. The
  bridge exposes model allocation and train segments, not presentation colors or an inferred
  navigable path. No failed or unavailable collection is treated as complete observation.
- BepInEx macOS ARM64 and x86_64 binaries are present, but the observed Steam process uses
  x86_64/Rosetta. Native ARM64 and Windows x64 are not claimed as live-validated.
- Route cancellation, train dispatch, construction, time changes, ongoing automation, arbitrary
  method calls, and multi-action objectives are unsupported. The bridge action catalog is empty.
  The UI catalog contains only `set_route_ui`, and an executed click is never retried.
- The canonical Sim Pilot Test Yard must be used for mutation proof. Prague supplies Phase 2
  observation evidence only; ordinary gameplay is not an accepted mutation target.
- Bridge launch must use Steam's Play button with the documented temporary `%command%` wrapper.
  Dock/Finder/Spotlight launches bypass that option and can select the unsupported ARM64 slice.
- UI route results are appended as owner-only JSONL evidence without screenshot pixels. This is a
  bounded objective trace, not continuous delegated automation.

## Deferred decisions

The following require product or operational direction rather than a documentation-only fix:

- whether to introduce a long-running worker or multi-task execution model;
- package publication, deployment, backups, and data-retention policy;
- security-scanner ownership and CI failure thresholds;
- remote-service authentication, authorization, encryption, and tenant isolation;
- further OpenTTD observation surfaces or actions beyond the two verified writes;
- field-by-field live promotion of Rail Route semantic observation and any later separately governed
  named gameplay action;
- a managed retention policy for provider and evaluation recordings.
