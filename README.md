# Sim Pilot

Sim Pilot is a local Python runtime that converts natural-language objectives into validated,
verified actions against deterministic simulations. It includes a reference simulation, durable
SQLite task execution, explicit OpenAI and authenticated Codex CLI providers, and a bounded
OpenTTD 15.3 integration. A version-pinned macOS Rail Route control slice supports verified
pause/resume commands from a plain-English terminal session.

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

## Control Rail Route

Rail Route 2.3.24 on macOS can be observed and paused or resumed through its own Space binding.
Sim Pilot validates that an active single-player game view is visible, sends at most one input,
then verifies the selected time control from a new screen observation:

```bash
uv run sim-pilot rail-route doctor
uv run sim-pilot rail-route status
uv run sim-pilot rail-route do "pause the game"
uv run sim-pilot rail-route do "resume the game"
uv run sim-pilot rail-route play
```

The interactive prompt accepts plain-English status, pause, and resume instructions. Named trains,
signals, platforms, and route-setting remain unsupported until the game exposes a semantic identity
and independently verifiable postcondition. See the
[Rail Route control guide](docs/023-rail-route-control.md).

## Architecture at a glance

```text
CLI -> Runtime -> Domain <- Adapters
        |                  |
        v                  v
   Persistence       Simulation / OpenTTD / Rail Route
```

- `sim_pilot.domain` owns strict public models.
- `sim_pilot.runtime` owns the one-action lifecycle, validation, verification, and recovery.
- `sim_pilot.reference_simulation` is a standalone deterministic engine.
- `sim_pilot.adapters` translates simulation-specific behavior into domain contracts.
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
