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

## Rail Route semantic bridge

The bridge host is fixed to `127.0.0.1`; no environment variable can broaden its bind or client
target. The token is generated during explicit installation and is not supplied on the command line.

| Variable | Default | Purpose |
|---|---:|---|
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_PORT` | `18461` | Loopback TCP port, from 1 through 65535. |
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_ARCHITECTURE` | `x86_64` | Exact expected game process architecture; use `arm64` only for a deliberate native launch. |
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_TOKEN_FILE` | platform owner-data directory | Owner-only random authentication token shared by client and plugin. |
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_CONNECTION_TIMEOUT_SECONDS` | `5` | Positive connect and handshake timeout. |
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_READ_TIMEOUT_SECONDS` | `5` | Positive framed-message read timeout. |
| `SIM_PILOT_RAIL_ROUTE_BRIDGE_MAXIMUM_MESSAGE_BYTES` | `1048576` | Positive limit no greater than the protocol-v3 ceiling. |

There is no Rail Route bridge write flag. Game Bridge Protocol v3 has an empty action catalog;
configuration cannot widen it, enable retries, or expose arbitrary methods. UI capability is
restricted in code to the canonical Test Yard.

## Software Inc.

The Software Inc. CLI discovers Steam app `362620` from the current macOS user's Steam library and
uses no credentials, network listener, hosted service, write-enable flag, or environment
configuration. The official lifecycle probe state is owner-only under
`~/Library/Application Support/Sim Pilot/software-inc/probe`. The Phase 2 bridge reads its
owner-only token and loopback port configuration as documented in
`028-software-inc-semantic-bridge.md`.

UI control has no write-enable environment variable. Phase 4 adds version-pinned `create_team`,
`observe_applicants`, and `hire_employee` workflows, but every commitment requires an exact
interactive approval. General environment configuration cannot bypass the team-name, applicant,
search-cost, salary-cap, session, or save checks. Owner-only trace paths are
`~/Library/Application Support/Sim Pilot/software-inc/ui/traces.jsonl` and
`~/Library/Application Support/Sim Pilot/software-inc/ui/staffing-traces.jsonl`. Screenshot pixels
are not retained by default.

Prompt 5 adds no general purchase or server-creation flag. Schedule and role requests are
constrained in code to one exact team, supported whole-hour bounds or one exact employee and
supported role. Prompt 5B workstation purchase uses an interactive default-no exact itemized
approval; environment configuration cannot bypass it. The destructive live acceptance has a
separate test-only gate and must be used only with an approved disposable company.

Prompt 6A contract acceptance, imminent deadline risk, exactly configured review spending,
promotion, and release are interactive default-no approvals. No environment variable bypasses
those prompts. Its live-test gate authorizes only market navigation, recommendation, and save-byte
non-mutation proof.

Prompt 6B Education uses an interactive default-no exact employee/course/cost approval. No
environment variable authorizes its final commitment. Its live-test gate permits reversible
navigation only up to the pending approval and requires unchanged save bytes.

Prompt 7 Atlas creation, exact review spending, iteration, and each Design-to-Alpha or
Alpha-to-Beta transition use separate interactive default-no approvals. No environment variable
bypasses those prompts or the conservative reserve. Its standard live gate permits reversible
design setup only up to a pending approval or a safe policy rejection and requires unchanged save
bytes.

Windows paths are represented only by design helpers and are not selected by the Prompt 1 CLI.

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
| `SIM_PILOT_LIVE_RAIL_ROUTE=1` | Existing screen-control pause/resume test; requires a disposable visible game. |
| `SIM_PILOT_LIVE_RAIL_ROUTE_BRIDGE=1` | Read-only bridge handshake, identity, snapshot, reconnect, and non-mutation suite on a disposable game. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_BRIDGE=1` | Read-only Software Inc. bridge acceptance on a paused disposable company. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_UI=1` | Exact-window Phase 3 UI acceptance on the supported disposable company; permits only its bounded catalog. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_GUIDANCE=1` | Guided terminal acceptance on the paused disposable company; permits one verified `open_manage_teams` delegation and checks save non-mutation. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_OFFICE=1` | Prompt 5 office-readiness, questions, empty-action, zero-input idempotence, and save-byte proof on a paused disposable company. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_WORKSTATION=1` | Destructive Prompt 5B room-assignment and exact workstation-purchase acceptance; use only after reviewing the disposable-company plan. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_CONTRACTS=1` | Read-only Prompt 6A market/recommendation and save-byte proof on a paused contract-ready disposable company. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_TRAINING=1` | Prompt 6B observation and reversible navigation to pending approval with save-byte non-mutation proof. |
| `SIM_PILOT_LIVE_SOFTWARE_INC_PRODUCTS=1` | Prompt 7 catalog/design preflight and reversible navigation to pending approval with save-byte non-mutation proof. |

These gates authorize a test to attempt external access; they do not configure credentials or the
OpenTTD connection themselves.

The Prompt 5B test also accepts `SIM_PILOT_SOFTWARE_INC_WORKSTATION_TEAM` (default `Core`) and
`SIM_PILOT_SOFTWARE_INC_WORKSTATION_RESERVE` (default `0`). These scope only the opt-in test; they do
not authorize normal CLI purchases.

The Prompt 6A read-only test also accepts `SIM_PILOT_SOFTWARE_INC_CONTRACT_TEAM` (default `Core`),
`SIM_PILOT_SOFTWARE_INC_CONTRACT_MINIMUM_REWARD` (default `0`), and
`SIM_PILOT_SOFTWARE_INC_CONTRACT_RESERVE` (default `0`). These select the exact recommendation
policy only; they do not authorize acceptance or any later contract commitment.

The Prompt 6B live test accepts `SIM_PILOT_SOFTWARE_INC_TRAINING_TEAM` (default `Core`) and
`SIM_PILOT_SOFTWARE_INC_TRAINING_RESERVE` (default `0`). These scope recommendation and navigation
only; they do not approve or start Education.

The Prompt 7 live test accepts `SIM_PILOT_SOFTWARE_INC_PRODUCT_RESERVE` (default `50000`). It scopes
only the conservative preflight and cannot approve creation, reviews, iterations, promotions, or
time advancement. Product workflows are owner-only under
`~/Library/Application Support/Sim Pilot/software-inc/products/workflows.sqlite3`.
