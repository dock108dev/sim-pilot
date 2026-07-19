# Operations and CLI

## Database selection and migrations

`sim_pilot.config.database_url` is the database-location source of truth. It resolves, in order:

1. an explicit CLI or programmatic value;
2. `SIM_PILOT_DATABASE`;
3. `data/sim-pilot.db`.

Application and raw Alembic commands use the same environment setting:

```bash
export SIM_PILOT_DATABASE=/tmp/sim-pilot-demo.db
uv run sim-pilot db upgrade
uv run alembic current
```

Application code must not use `metadata.create_all()` or ad hoc production DDL. Alembic owns the
schema. Database, journal, and WAL files are restricted to the owning user.

See [configuration.md](configuration.md) for configuration precedence and the complete environment
variable reference. See [data-models.md](data-models.md) before changing serialized or persisted
data.

## Durable reference task

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
uv run sim-pilot task resume \
  00000000-0000-0000-0000-000000000123 \
  --decision-provider scripted
```

`task create --spec task.json` accepts a serialized `TaskSpecification`. Without `--spec` or
`--instruction`, it creates the deterministic cash-target demo.

## Compiler and decision providers

Compiler and runtime decision providers are independent. The default is `none`, which fails before
making a hosted call. There is no automatic fallback.

### Authenticated Codex CLI

The Codex provider uses the local authenticated CLI rather than `OPENAI_API_KEY`:

```bash
command -v codex
codex --version
codex login status

uv run sim-pilot task compile \
  --provider codex \
  --model gpt-5.6-sol \
  --instruction "Reach one million cash without taking loans"
```

Use it for runtime decisions by selecting it separately:

```bash
uv run sim-pilot task run TASK_ID \
  --decision-provider codex \
  --decision-model gpt-5.6-sol
```

Codex calls use an owner-only temporary directory outside Git repositories, ephemeral mode,
read-only sandboxing, disabled shell capability, approval policy `never`, bounded output, stdin
prompt delivery, JSONL telemetry, and a strict output schema.

The complete Codex setting list, including output bounds, raw-event diagnostics, and defaults, is
maintained in [configuration.md](configuration.md).

A configured temporary root inside a Git repository is rejected.

### OpenAI API

```bash
export OPENAI_API_KEY="..."
export SIM_PILOT_COMPILER_MODEL="gpt-5.6"
export SIM_PILOT_DECISION_MODEL="gpt-5.6"
export SIM_PILOT_DECISION_TIMEOUT_SECONDS="30"

uv run sim-pilot task compile \
  --provider openai \
  --instruction "Reach one million cash without taking loans"
uv run sim-pilot task run TASK_ID --decision-provider openai
```

Automated tests never require paid calls.

## Recordings

Compiler and decision recordings are separate and opt-in:

```bash
uv run sim-pilot task compile \
  --provider codex \
  --record-dir ./data/compiler-recordings \
  --instruction "Reach one million cash"
uv run sim-pilot task run TASK_ID \
  --decision-provider codex \
  --record-dir ./data/decision-recordings
```

Recordings are atomically replaced and stored with owner-only permissions. They can contain prompts,
instructions, structured responses, and game state. Do not commit them.

## OpenTTD 15.3

Use only a loopback-bound disposable server. Configure the Admin Network as described in
[003-openttd-integration.md](003-openttd-integration.md), then run:

```bash
export SIM_PILOT_OPENTTD_ADMIN_PASSWORD="..."
uv run sim-pilot openttd doctor
uv run sim-pilot openttd capabilities
uv run sim-pilot openttd observe
uv run sim-pilot openttd watch --count 5
```

The Admin Network write boundary is separately disabled by default:

```bash
export SIM_PILOT_OPENTTD_ALLOW_WRITES=1
uv run sim-pilot openttd action set-server-name "Sim Pilot Local Test"
```

For GameScript installation and exact protocol requirements, read
[005-openttd-bridge-protocol.md](005-openttd-bridge-protocol.md). Bridge composition and writes use
independent flags:

```bash
export SIM_PILOT_OPENTTD_GS_ENABLED=1
uv run sim-pilot openttd bridge doctor
uv run sim-pilot openttd bridge capabilities
uv run sim-pilot openttd bridge observe

uv run sim-pilot openttd world
uv run sim-pilot openttd towns
uv run sim-pilot openttd industries
uv run sim-pilot openttd stations
uv run sim-pilot openttd vehicles
uv run sim-pilot openttd company
uv run sim-pilot openttd routes
uv run sim-pilot openttd diff --wait-seconds 1

export SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1
uv run sim-pilot openttd bridge action set-company-name "Sim Pilot Test"
```

The two supported live actions are `set_server_name` and `set_company_name`. Route construction,
vehicle control, and public multiplayer automation are not supported.
The world commands are read-only and accept `--json`; their model, coverage, route inference, and
diff rules are documented in [013-openttd-world-observation.md](013-openttd-world-observation.md).

## Approval and recovery

Approval commands take an approval ID. Inspect the task and events before changing recovery state:

```bash
uv run sim-pilot task show TASK_ID
uv run sim-pilot task events TASK_ID
uv run sim-pilot task recovery show TASK_ID
uv run sim-pilot task recovery resolve TASK_ID mark_not_executed
uv run sim-pilot task approve APPROVAL_ID
uv run sim-pilot task deny APPROVAL_ID
uv run sim-pilot task cancel TASK_ID
```

`recovery show` accepts `--snapshot snapshot.json` when current adapter state is independently
observable. Never retry an action while an interrupted attempt remains unresolved. Sim Pilot does
not claim exactly-once external execution.

Unexpected runtime failures are durably recorded when storage remains available. If persistence
itself fails, preserve the database and sidecars and diagnose before retrying. The detailed failure
matrix and operator response are in [015-abend-handling.md](015-abend-handling.md).

Exit codes are:

| Code | Meaning |
|---:|---|
| 0 | success or committed slice |
| 10 | approval required |
| 11 | recovery required |
| 12 | blocked |
| 13 | failed |
| 14 | cancelled |
| 20 | invalid input or provider selection |
| 21 | persistence or reconstruction failure |
| 22 | migration failure |
| 23 | OpenTTD configuration, connection, protocol, or action failure |

CLI errors include their typed exception class: `error[ExceptionType]: message`.

## Product evaluation

The bounded evaluation runner requires explicit compiler and decision providers and writes private,
resumable evidence:

```bash
uv run sim-pilot evaluate product \
  --compiler-provider codex \
  --decision-provider codex \
  --compiler-model gpt-5.6-sol \
  --decision-model gpt-5.6-sol \
  --max-runtime-iterations 8 \
  --record-dir ./data/product-evaluation
```

OpenAI evaluation additionally requires current input/output token prices. Evaluation results may
contain prompts and user instructions and must not be committed.

## Crash-window demonstration

```bash
uv run python scripts/demo_crash_recovery.py
```

The demo stops after adapter execution, reconstructs a fresh runtime over the same SQLite database,
classifies independently retained state, and resolves without retrying the action.

## Deployment and background processing

There is no server process, scheduler, worker, service manager, container image, or deployment
configuration in this repository. Commands run synchronously in the invoking process. Durable
SQLite state supports later `task resume` invocations, but no component automatically discovers or
resumes tasks. Current operational boundaries are listed in
[known-limitations.md](known-limitations.md).
