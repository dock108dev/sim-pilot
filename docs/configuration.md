# Environment and Configuration

Sim Pilot is configured through CLI options and environment variables. It does not load `.env`
files. Export values in the invoking shell or pass the corresponding CLI option. Local `.env*`
files are ignored to reduce accidental secret commits.

## Precedence

Where both exist, an explicit CLI or programmatic argument wins over an environment variable. The
environment variable wins over the source default. Database selection follows this rule through
`sim_pilot.config.database_url`; OpenTTD configuration is loaded by
`sim_pilot.openttd.config.openttd_configuration`.

## Core runtime and model providers

| Variable | Default | Purpose |
|---|---:|---|
| `SIM_PILOT_DATABASE` | `data/sim-pilot.db` | SQLite file path or `sqlite:///...` URL used by the CLI and Alembic. |
| `SIM_PILOT_COMPILER_MODEL` | `gpt-5.6` | OpenAI compiler model when no `--model` is supplied. |
| `SIM_PILOT_DECISION_MODEL` | `gpt-5.6` | OpenAI decision model when no `--decision-model` is supplied. |
| `SIM_PILOT_DECISION_TIMEOUT_SECONDS` | `30` | Positive OpenAI decision request timeout. |
| `SIM_PILOT_ANALYSIS_SESSION_DIRECTORY` | `data/analysis-session` | Owner-only analysis records, retained snapshots, and the bounded live snapshot cache. |
| `OPENAI_API_KEY` | unset | Credential consumed by the OpenAI SDK when the OpenAI provider is explicitly selected. |

The compiler and decision providers default to `none`; setting a model or credential does not
select a provider. Choose `--provider openai` or `--decision-provider openai` explicitly.

## Authenticated Codex CLI provider

| Variable | Default | Purpose |
|---|---:|---|
| `SIM_PILOT_CODEX_MODEL` | `gpt-5.6-sol` | Codex model used for compiler and decision requests. |
| `SIM_PILOT_CODEX_EXECUTABLE` | discovered on `PATH` | Optional exact Codex executable path. |
| `SIM_PILOT_CODEX_TIMEOUT_SECONDS` | `120` | Positive subprocess timeout. |
| `SIM_PILOT_CODEX_TEMPORARY_ROOT` | system temporary directory | Parent for owner-only isolated invocation directories; Git worktrees are rejected. |
| `SIM_PILOT_CODEX_MAXIMUM_STDOUT_BYTES` | `2000000` | Positive JSONL stdout limit. |
| `SIM_PILOT_CODEX_MAXIMUM_STDERR_BYTES` | `64000` | Positive stderr limit. |
| `SIM_PILOT_CODEX_CAPABILITY_CACHE_SECONDS` | `60` | Non-negative lifetime for CLI capability probes. |
| `SIM_PILOT_CODEX_PRESERVE_DEBUG_DIRECTORY` | `0` | Set to `1` to retain the invocation directory and sanitized diagnostics. |
| `SIM_PILOT_CODEX_RECORD_RAW_EVENTS` | `0` | Set to `1` to retain sanitized raw JSONL events and the invocation directory. |

The Codex provider launches the separately authenticated `codex` executable. Sim Pilot does not
read Codex account tokens and removes OpenAI/Codex token variables from the child environment. The
subprocess may use the network according to the Codex CLI account and installation.

## OpenTTD 15.3

| Variable | Default | Purpose |
|---|---:|---|
| `SIM_PILOT_OPENTTD_ADMIN_PASSWORD` | required | Admin Network password, held as a Pydantic secret. |
| `SIM_PILOT_OPENTTD_HOST` | `127.0.0.1` | Admin host; validation rejects any host resolving outside loopback. |
| `SIM_PILOT_OPENTTD_PORT` | `3977` | Admin Network TCP port. |
| `SIM_PILOT_OPENTTD_COMPANY_ID` | `0` | Company slot, from 0 through 14, used by the GameScript bridge. |
| `SIM_PILOT_OPENTTD_VERSION` | `15.3` | Expected server version. |
| `SIM_PILOT_OPENTTD_CONNECTION_TIMEOUT_SECONDS` | `5` | Positive connect/handshake timeout. |
| `SIM_PILOT_OPENTTD_OBSERVATION_TIMEOUT_SECONDS` | `5` | Positive observation and bridge timeout. |
| `SIM_PILOT_OPENTTD_POLL_INTERVAL_SECONDS` | `1` | Poll interval; configuration requires at least 0.1 seconds. |
| `SIM_PILOT_OPENTTD_ACTION_TIMEOUT_SECONDS` | `5` | Positive action verification timeout. |
| `SIM_PILOT_OPENTTD_STALE_THRESHOLD_DAYS` | `3` | Non-negative game-date staleness threshold. |
| `SIM_PILOT_OPENTTD_ALLOW_WRITES` | `0` | Set to `1` to enable the Admin RCON `set_server_name` action. |
| `SIM_PILOT_OPENTTD_GS_ENABLED` | `0` | Set to `1` to compose the GameScript bridge. |
| `SIM_PILOT_OPENTTD_GS_ALLOW_WRITES` | `0` | Set to `1` to enable the bridge `set_company_name` action. |
| `SIM_PILOT_OPENTTD_EXECUTABLE` | unset | Optional local executable used by doctor diagnostics. |
| `SIM_PILOT_OPENTTD_REQUIRED_SCRIPT` | unset | Optional expected GameScript path used by doctor diagnostics. |
| `SIM_PILOT_OPENTTD_SAVE_PATH` | unset | Optional save path used by doctor diagnostics. |

Boolean OpenTTD settings accept only `0` or `1`. The Admin and GameScript write switches are
independent and should be enabled only for a disposable local server.

## Opt-in live-test gates

The default test suite skips live access. These variables are read only by live tests:

| Gate | Additional requirement |
|---|---|
| `SIM_PILOT_LIVE_COMPILER=1` | `OPENAI_API_KEY`; enables the live OpenAI compiler test. |
| `SIM_PILOT_LIVE_DECISION=1` | `OPENAI_API_KEY`; enables the live OpenAI decision test. |
| `SIM_PILOT_LIVE_CODEX=1` plus `SIM_PILOT_LIVE_CODEX_COMPILER=1` | Authenticated compatible Codex CLI. |
| `SIM_PILOT_LIVE_CODEX=1` plus `SIM_PILOT_LIVE_CODEX_DECISION=1` | Authenticated compatible Codex CLI. |
| `SIM_PILOT_LIVE_OPENTTD=1` | Disposable loopback OpenTTD 15.3 server; writes also require `SIM_PILOT_OPENTTD_ALLOW_WRITES=1`. |
| `SIM_PILOT_LIVE_OPENTTD_GS=1` | Installed bridge; writes also require `SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1`. |
| `SIM_PILOT_LIVE_OPENTTD_INTELLIGENCE=1` | Read-only live world collection and deterministic intelligence. |
| `SIM_PILOT_LIVE_CODEX_INTELLIGENCE=1` plus the OpenTTD intelligence gate | Authenticated Codex compilation or explanation over bounded inputs. |
| `SIM_PILOT_LIVE_OPENTTD_INTERACTION=1` | Phase 9 read-only live interaction regression. |
| `SIM_PILOT_LIVE_CODEX_INTERACTION=1` plus the Phase 9 OpenTTD gate | Phase 9 Codex regression, capped by the test plan at two invocations. |
| `SIM_PILOT_LIVE_OPENTTD_LATENCY=1` | Phase 9.2 read-only cold and compatible-cache latency checks. |
| `SIM_PILOT_LIVE_OPENTTD_INSPECTION=1` | Phase 10A read-only inspection-capability verification; no UI or economic action is sent. |

These gates authorize a test to attempt external access; they do not configure credentials or the
OpenTTD connection themselves.
