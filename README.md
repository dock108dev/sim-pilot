# Sim Pilot

Sim Pilot is a local Python runtime that converts natural-language objectives into validated,
verified actions against deterministic simulations. It includes a reference simulation, durable
SQLite task execution, explicit OpenAI and authenticated Codex CLI providers, and retained OpenTTD,
Rail Route, and Software Inc. integrations. Software Inc. is frozen as a reference capability: its
implemented discovery, observation, guidance, approval, and visible-UI work remains available for
maintenance and reuse, but its game-specific roadmap is no longer the default product direction.

The frozen Software Inc. terminal also acts as a teacher and advisor. It answers from live observations
and versioned repository knowledge, offers a short crash course, recommends one bounded next
objective, and mutates the game only after explicit delegation to a currently compatible,
live-proven action.

No successor game has been selected. The next product decision must first prove a short,
terminal-first, plain-English-to-visible-result loop in a game the player actually wants to play.
See the [freeze checkpoint](docs/037-software-inc-freeze-checkpoint.md).

The runtime executes one action per cycle and treats every model-produced decision as untrusted
until deterministic policy and adapter validation succeed. Model-backed providers and live-game
access are opt-in; the normal test suite is offline.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12, installed automatically by uv when needed

The project does not require a `python` executable on `PATH`. Use `uv run` for project commands.

## Setup

```bash
uv python install 3.12
uv sync --dev
```

## Validate the repository

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

These are the same checks run by GitHub Actions.

## Run the deterministic local flow

Create a disposable database, create a reference-simulation task, and execute one iteration:

```bash
export SIM_PILOT_DATABASE=/tmp/sim-pilot-demo.db

uv run sim-pilot db upgrade
uv run sim-pilot task create \
  --task-id 00000000-0000-0000-0000-000000000123 \
  --target-cash 520000
uv run sim-pilot task run \
  00000000-0000-0000-0000-000000000123 \
  --decision-provider scripted \
  --iterations 1
uv run sim-pilot task show 00000000-0000-0000-0000-000000000123
uv run sim-pilot task events 00000000-0000-0000-0000-000000000123
```

The `scripted` decision provider is deterministic and performs no hosted call.

## Compile a natural-language task

Providers are always explicit; there is no fallback from an unconfigured provider to a hosted
provider. For example, with an authenticated local Codex CLI session:

```bash
codex login status
uv run sim-pilot task compile \
  --provider codex \
  --instruction "Reach one million cash without taking loans"
```

Compiler and runtime decision providers are selected independently. See the
[operations guide](docs/operations.md) for OpenAI configuration and runtime-provider commands.

## OpenTTD

The supported live integration targets a loopback-bound OpenTTD 15.3 server. After configuring its
Admin Network password:

```bash
export SIM_PILOT_OPENTTD_ADMIN_PASSWORD="..."
uv run sim-pilot openttd doctor
uv run sim-pilot openttd world
```

Writes remain disabled unless their separate safety flags are enabled on a disposable server. See
[OpenTTD integration](docs/003-openttd-integration.md) and the
[GameScript bridge protocol](docs/005-openttd-bridge-protocol.md) before enabling them.
The canonical model and its explicit coverage limits are documented in
[OpenTTD world observation](docs/013-openttd-world-observation.md).

## Analyze OpenTTD

Gameplay analysis is read-only and separate from action tasks. It works deterministically from a
saved snapshot or verified live state without a model. When no snapshot file is supplied, the
OpenTTD intelligence commands reuse a compatible snapshot up to five seconds old after a live
identity probe, or collect fresh state when needed:

```bash
uv run sim-pilot ask --snapshot snapshot.json "Why am I losing money?"
uv run sim-pilot ask "Which vehicles lost the most money last year?"
uv run sim-pilot openttd analyze vehicles --fresh
uv run sim-pilot analysis show
uv run sim-pilot analysis inspect ANALYSIS_ID FINDING_ID
```

Codex or OpenAI compilation and explanation are optional and must be selected explicitly with
`--compiler-provider` and `--explanation-provider`. The
[OpenTTD intelligence guide](docs/016-openttd-intelligence-guide.md) covers supported questions,
freshness, evidence drill-down, and limitations. Named client-window inspection currently returns
`unsupported` because the proven OpenTTD boundary has no verifiable viewport postcondition.

## Frozen Software Inc. reference capability

Software Inc. remains registered without generic persisted-task gameplay authority. Its roadmap is
frozen at this checkpoint: the commands below preserve the reviewed capability and evidence but do
not authorize another Software Inc. milestone or imply that it is the next product target. The
discovery commands inspect the exact installation/runtime and manage one official lifecycle probe:

```bash
uv run sim-pilot software-inc doctor
uv run sim-pilot software-inc doctor --json
uv run sim-pilot software-inc capabilities
uv run sim-pilot software-inc crash-course
uv run sim-pilot software-inc ask "What do teams do?"
uv run sim-pilot software-inc ask "How many employees do I have?"
uv run sim-pilot software-inc recommend
uv run sim-pilot software-inc play
uv run sim-pilot software-inc probe doctor
uv run sim-pilot software-inc probe install
uv run sim-pilot software-inc probe verify
uv run sim-pilot software-inc probe disable
uv run sim-pilot software-inc probe uninstall
```

File-changing probe commands require the game to be closed. After the first install, launch the
game and enable `SimPilotDiscoveryProbe` once in **Mods → Code mods**; Software Inc. owns that
explicit activation setting. The probe exposes no gameplay state or actions. See the
[Software Inc. foundation](docs/027-software-inc-foundation.md).

The separate Phase 2 bridge adds authenticated, read-only semantic observation while keeping the
gameplay action catalog empty:

```bash
uv run sim-pilot software-inc bridge doctor
# Close the game before the next command.
uv run sim-pilot software-inc bridge install --approve-broad-access
uv run sim-pilot software-inc bridge verify
# Relaunch, enable Sim Pilot Read-Only Bridge, load a company, and pause.
uv run sim-pilot software-inc bridge observe
uv run sim-pilot software-inc bridge list teams
uv run sim-pilot software-inc bridge list employees
uv run sim-pilot software-inc bridge prove-read-only
```

The approval grants Software Inc.'s compiled-mod access only for the owner-only token read and
loopback listener. See the [Phase 2 operating guide](docs/028-software-inc-semantic-bridge.md).

Phase 3 keeps that bridge read only and adds a separate visible-UI catalog:

```bash
uv run sim-pilot software-inc ui doctor
uv run sim-pilot software-inc ui observe
uv run sim-pilot software-inc ui capabilities
uv run sim-pilot software-inc ui do "pause the game"
uv run sim-pilot software-inc ui do "resume the game"
uv run sim-pilot software-inc ui do "open manage teams"
```

Every cycle sends at most one frame-bound gesture and verifies it from a new synchronized
screenshot and semantic observation. See the
[Phase 3 UI-control guide](docs/029-software-inc-verified-ui-control.md).

Phase 4 keeps bridge mutation authority empty and adds player-visible staffing workflows:

```bash
uv run sim-pilot software-inc ui do "create a team named Support Alpha"
uv run sim-pilot software-inc ui do \
  "hire one programmer for Support Alpha for no more than $8,000 per month"
```

The CLI asks separately before a paid applicant search and before the chosen applicant's recurring
monthly salary. These Phase 4 operations remain unavailable through the Guided Operator until their
separate live mutation gate passes. See the
[Phase 4 teams-and-hiring guide](docs/030-software-inc-teams-and-hiring.md).

Prompt 5 adds office advice and bounded schedule/role control. Prompt 5B adds exact,
approval-gated visible workstation setup:

```bash
uv run sim-pilot software-inc office readiness Core
uv run sim-pilot software-inc crash-course office
uv run sim-pilot software-inc crash-course schedules
uv run sim-pilot software-inc crash-course servers
uv run sim-pilot software-inc ask "Does Core have enough desks?"
uv run sim-pilot software-inc ask "What hours does Core work?"
uv run sim-pilot software-inc ui do "set Core working hours to 8-16" --dry-run
uv run sim-pilot software-inc ui do "assign Gage Chen as Programmer for Core" --dry-run
uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve" --dry-run
uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve"
```

The live form prints the exact room, catalog bundle, item prices, projected cash, fixed recurring
cost, and utility unknown before default-no confirmation. It places only after a fresh green preview
in the exact target room. See the [Prompt 5 office-readiness guide](docs/032-software-inc-office-readiness.md)
and [Prompt 5B workstation guide](docs/033-software-inc-workstation-placement.md).

Prompt 6A adds the first approval-bound contract lifecycle:

```bash
uv run sim-pilot software-inc crash-course contracts
uv run sim-pilot software-inc contracts do \
  "find a small contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts do \
  "accept the recommended contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts do "advance the current contract" --seconds 10
uv run sim-pilot software-inc contracts do "review the current contract"
uv run sim-pilot software-inc contracts do "promote the current contract"
uv run sim-pilot software-inc contracts do "release the current contract"
```

Acceptance, imminent deadline risk, exactly priced review, promotion, and release use separate
default-no prompts. See the [Prompt 6A first-contract guide](docs/034-software-inc-first-contract.md).

Prompt 6B adds the first approval-bound education assignment:

```bash
uv run sim-pilot software-inc crash-course training
uv run sim-pilot software-inc training do \
  "recommend one suitable employee from Core for System design education while keeping $50,000 in cash"
uv run sim-pilot software-inc training do \
  "train one suitable employee from Core in System design for three months while keeping $50,000 in cash"
uv run sim-pilot software-inc training do "advance training" --seconds 10
uv run sim-pilot software-inc training do "training status"
```

The objective is implemented as three sequential one-month courses. Each commitment prompt names
the exact employee, current-level cost, continuing payroll, temporary team capacity, cash after the
charge, and reserve; later courses require fresh approval. Every bounded advance returns the game
to pause and completion requires System level 3. See the
[Prompt 6B training guide](docs/035-software-inc-first-training-assignment.md).

Prompt 7 adds the first controlled software-product lifecycle:

```bash
uv run sim-pilot software-inc crash-course products
uv run sim-pilot software-inc products types
uv run sim-pilot software-inc products features --type "Game Engine"
uv run sim-pilot software-inc products start --minimum-cash-reserve 50000 --dry-run
uv run sim-pilot software-inc products do \
  "begin a small game engine called Atlas using Core and keep $50,000 in reserve"
uv run sim-pilot software-inc products do "advance Atlas" --seconds 10
uv run sim-pilot software-inc products do "review Atlas"
uv run sim-pilot software-inc products do "iterate Atlas"
uv run sim-pilot software-inc products do "promote Atlas"
```

The Advisor credits no forecast revenue and rejects configurations whose observed payroll and
infrastructure runway would cross the reserve. Creation, reviews, iterations, and both promotions
use separate default-no approvals. Every bounded advance returns the game to pause, and Prompt 7
stops at verified Beta without releasing the product. See the
[Prompt 7 Atlas guide](docs/036-software-inc-first-product-atlas.md).

Inside `software-inc play`, use `/crash_course`, `/status`, `/recommend`, `/why`, `/capabilities`,
and `/operate <objective>`. Questions and recommendations never send UI input. Unsupported or
offline-only objectives fail closed. See the
[Guided Operator guide](docs/031-software-inc-guided-operator-and-game-knowledge.md).

## Retained Rail Route integration

Rail Route 2.3.24 on macOS can be observed and paused or resumed through its own Space binding.
Sim Pilot validates that an active single-player game view is visible, sends at most one input,
then verifies the selected time control from a new screen observation:

```bash
uv run sim-pilot rail-route doctor
uv run sim-pilot rail-route status
uv run sim-pilot rail-route do "pause the game"
uv run sim-pilot rail-route do "resume the game"
uv run sim-pilot rail-route ui doctor
uv run sim-pilot rail-route do "set a route from SIG-W-IN to SIG-C-W" --dry-run
uv run sim-pilot rail-route do "set a route from SIG-W-IN to SIG-C-W"
uv run sim-pilot rail-route play
```

The interactive prompt accepts plain-English status, pause, resume, and the exact UI route syntax
above. Route-setting requires the read-only bridge and the paused canonical Test Yard. See the
[Rail Route control guide](docs/023-rail-route-control.md).

An independently versioned, opt-in semantic bridge adds authenticated read-only snapshots. UI
capabilities are negotiated separately and the bridge action catalog remains empty:

```bash
uv run sim-pilot rail-route bridge doctor
uv run sim-pilot rail-route bridge install
uv run sim-pilot rail-route bridge verify
uv run sim-pilot rail-route bridge capabilities
uv run sim-pilot rail-route bridge observe --json
uv run sim-pilot rail-route bridge list trains
uv run sim-pilot rail-route bridge list incoming-traffic
uv run sim-pilot rail-route bridge list track-occupancy
uv run sim-pilot rail-route bridge show trains <UUID-or-reporting-number>
uv run sim-pilot rail-route bridge prove-read-only
uv run sim-pilot rail-route bridge disable
uv run sim-pilot rail-route bridge uninstall
```

Installation is pinned and manifest-owned; it refuses a running game, unexpected version/hash,
symlink, or collision. See the [semantic bridge guide](docs/025-rail-route-semantic-bridge.md).

## Architecture at a glance

```text
CLI -> Runtime -> Domain <- Adapters
        |                  |
        v                  v
   Persistence       Reference / OpenTTD / Rail Route / Software Inc.
```

- `sim_pilot.domain` owns strict public models.
- `sim_pilot.runtime` owns the one-action lifecycle, validation, verification, and recovery.
- `sim_pilot.reference_simulation` is a standalone deterministic engine.
- `sim_pilot.adapters` translates simulation-specific behavior into domain contracts.
- `sim_pilot.game_bridge` owns the game-neutral authenticated snapshot and atomic-action client.
- `sim_pilot.persistence` defines repository interfaces; SQLite remains below them.
- Provider-specific code stays behind compiler and decision-provider interfaces.

Every serialized domain model carries `schema_version=1`. Changes to `TaskSpecification`,
`Observation`, `Action`, or `Decision` require an accompanying RFC update.

## Documentation

- [Documentation index](docs/README.md)
- [Development and architecture guide](docs/development.md)
- [Environment and configuration](docs/configuration.md)
- [Operations and CLI guide](docs/operations.md)
- [Known limitations](docs/known-limitations.md)
- [Vision](docs/000-vision.md)
- [Runtime design](docs/001-month-1-design.md)
- [Reference simulation specification](docs/002-reference-simulation.md)

Release history is recorded in [CHANGELOG.md](CHANGELOG.md).
