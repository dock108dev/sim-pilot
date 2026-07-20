# Development and Architecture

## Local environment

Sim Pilot requires Python 3.12 and uses uv for environments, dependency locking, and commands.

```bash
uv python install 3.12
uv sync --dev
```

Use `uv run`; a system `python` executable is not required.

## Validation

Run the complete local gate before handing off a change:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Apply formatting with `uv run ruff format .`. CI installs from the lockfile and runs the same four
checks. Normal tests are deterministic and do not require OpenAI credentials, Codex authentication,
or OpenTTD.

Build the distributable wheel and source archive with:

```bash
uv build
```

Generated `dist/`, `build/`, and `*.egg-info` paths are ignored. Sim Pilot is currently operated
from a source checkout; there is no published package or deployment artifact.

Live tests are explicitly gated:

```bash
SIM_PILOT_LIVE_COMPILER=1 uv run pytest -m live \
  tests/intent_compiler/test_live_openai.py
SIM_PILOT_LIVE_DECISION=1 uv run pytest -m live \
  tests/decision_provider/test_live_openai.py
SIM_PILOT_LIVE_CODEX=1 SIM_PILOT_LIVE_CODEX_COMPILER=1 \
  uv run pytest -m live tests/intent_compiler/test_live_codex_cli.py
SIM_PILOT_LIVE_CODEX=1 SIM_PILOT_LIVE_CODEX_DECISION=1 \
  uv run pytest -m live tests/decision_provider/test_live_codex_cli.py
```

Only run live tests after authorizing the corresponding hosted usage or disposable game server.

## Package boundaries

| Package | Responsibility |
|---|---|
| `sim_pilot.domain` | Strict, versioned public task and action contracts. |
| `sim_pilot.reference_simulation` | Standalone deterministic state machine. |
| `sim_pilot.adapters` | Domain-facing wrappers around simulation-specific behavior. |
| `sim_pilot.runtime` | Lifecycle, policy, decision validation, verification, persistence coordination, and recovery. |
| `sim_pilot.intent_compiler` | Natural-language compilation and deterministic semantic validation. |
| `sim_pilot.decision_provider` | Model-backed runtime decision implementations. |
| `sim_pilot.analysis` | Read-only deterministic gameplay requests, analyzers, evidence, interaction composition, freshness, and local sessions. |
| `sim_pilot.analysis_provider` | Optional Codex CLI and OpenAI analysis compilers and explanations. |
| `sim_pilot.provider_support` | Shared provider subprocess support, currently the Codex CLI boundary. |
| `sim_pilot.persistence` | Repository and unit-of-work contracts plus in-memory storage. |
| `sim_pilot.persistence.sqlite` | SQLAlchemy repositories, schema, transactions, and Alembic helpers. |
| `sim_pilot.openttd` | Admin Network and GameScript protocol clients below the adapter boundary. |
| `sim_pilot.reconciliation` | Adapter-specific crash-window classification and application composition. |

Dependency direction is enforced by `tests/architecture/test_dependency_direction.py`:

```text
CLI -> Runtime -> Domain <- Adapter -> Reference Simulation
 |        |                    |
 |        v                    v
 |   Persistence contracts   OpenTTD client
 v
Compiler / Decision Provider interfaces
```

Adapters do not import runtime. Runtime does not import SQLite, OpenTTD, intent-compiler, or hosted
provider implementations. The OpenAI SDK is imported only by the two OpenAI providers.

### Runtime orchestration layout

The public `RuntimeEngine` facade delegates execution through small internal collaborators while
preserving one action and one atomic checkpoint per cycle:

- `runtime/engine.py`: public task, approval, cancellation, recovery, run, and resume facade.
- `runtime/execution.py`: adapter initialization, shutdown, and failure escalation.
- `runtime/iteration.py`: evaluate, decide, validate, and select the next cycle outcome.
- `runtime/action_execution.py`: crash-journaled execute, observe, verify, and checkpoint sequence.
- `runtime/execution_services.py`: typed dependency bundle shared by execution collaborators.
- `runtime/engine_support.py`: pure transition, snapshot, event, fingerprint, and outcome helpers.

`tests/architecture/test_dependency_direction.py` keeps these orchestration modules below 500 lines.
Crash-point order remains part of the runtime contract and is protected by restart tests.

## Public model changes

Every serialized domain model has `schema_version=1`. Treat `TaskSpecification`, `Observation`,
`Action`, and `Decision` as public interfaces. Update the applicable RFC and serialization tests
when changing them. Persisted payload changes require an explicit migration or compatibility
decision.

## Reference simulation development

The deterministic engine can be exercised without runtime or persistence:

```bash
uv run pytest tests/reference_simulation
uv run pytest tests/adapters/test_reference_adapter.py
```

Canonical deterministic states live in `tests/fixtures`. Given the same seed, state, and action
sequence, the simulation must produce identical results.

## Test organization

- `tests/domain`: public model contracts and invalid input.
- `tests/reference_simulation`: deterministic formulas, actions, and scenarios.
- `tests/runtime`: lifecycle, policy, verification, recovery, and durable restart.
- `tests/persistence`: repository contracts, transactions, and migrations.
- `tests/intent_compiler` and `tests/decision_provider`: provider boundaries and structured output.
- `tests/openttd`: protocol, adapter, GameScript, and opt-in live behavior.
- `tests/analysis`: request contracts, analyzers, evidence, compiler, explanation, CLI data, and
  separately gated live analysis.
- `tests/architecture`: import and dependency-direction guards.

Use scripted providers in automated tests. Do not add paid or authenticated calls to the default
suite.

`sim_pilot.analysis` is provider-, adapter-, persistence-, and runtime-independent.
`sim_pilot.analysis_provider` owns optional Codex/OpenAI implementations. Architecture tests enforce
that dependency direction and isolate the OpenAI SDK to provider modules.

All configuration keys and live-test gates are cataloged in
[configuration.md](configuration.md). Persistence contracts and schema ownership are described in
[data-models.md](data-models.md). The complete list of authoritative implementation paths, bounded
read-compatibility readers, and guard tests is maintained in
[016-ssot-enforcement.md](016-ssot-enforcement.md).

## Repository support surfaces

- `alembic/`: versioned durable schema migrations.
- `openttd_gamescript/sim_pilot_bridge/`: distributed GameScript bridge.
- `discovery/openttd_gamescript/`: retained Task 7A probes and sanitized discovery evidence; it is
  not production adapter code.
- `scripts/demo_crash_recovery.py`: deterministic crash-window demonstration.
- `scripts/profile_phase9_2_latency.py`: reproducible read-only collection profiler documented by
  the Phase 9.2 latency report.
- `scripts/run_founder_intelligence.py`, `scripts/assemble_founder_review.py`,
  `scripts/run_phase9_founder_review.py`, and `scripts/summarize_founder_sample.py`: milestone
  evidence generators retained so the dated founder-review artifacts can be reproduced. They are
  not normal operating entry points.

## Large cohesive modules

The following source modules remain over roughly 500 lines after review:

- `cli.py`: Typer command registration and monkeypatched CLI composition are currently one public
  process surface. Split by command group only with a focused CLI-module migration.
- `analysis/compiler.py`: deterministic parsing, conversation resolution, and provider-output
  normalization derive one request contract. Splitting them independently would risk intent drift.
- `analysis/analyzers/changes.py`: change, anomaly, entity-summary, and priority analyzers share
  typed change-evidence and severity helpers. A later analyzer-per-module move should be mechanical.
- `analysis/interaction.py`: direct answer, decisive-finding selection, inspection guidance, and
  limitations form one deterministic response-composition pipeline.
- `product_evaluation.py`: models, bounded call accounting, per-case execution, aggregation, and
  resumable file output form one evidence pipeline. A later split should preserve resumability.
- `analysis/contracts.py`: the strict request, evidence, finding, presentation, freshness, and
  response models are kept together as the analysis package's public schema surface.
- `provider_support/codex_cli/client.py`: subprocess lifecycle, parsing, diagnostics, isolation, and
  cleanup share security-sensitive state. Splitting it should be handled as a provider-boundary
  hardening change.
- `openttd/gamescript/client.py`: negotiation, identity, sequence validation, resynchronization, and
  paginated collection are one stateful bridge protocol client.

Large test modules mirror end-to-end scenarios and are retained as tests rather than production
architecture.
