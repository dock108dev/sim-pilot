# OpenTTD 15.3 Read-Only Integration

## Supported boundary

Task 6B supports OpenTTD **15.3** and Admin Network protocol **3**. The implementation was checked
against the official 15.3 tag at commit `14ec60f248547d4d062a1160f0fc26d742319888` and the published
[`admin_network.md`](https://github.com/OpenTTD/OpenTTD/blob/15.3/docs/admin_network.md) and
[`tcp_admin.h`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/tcp_admin.h)
contracts. Other OpenTTD releases fail version validation instead of being assumed compatible.

The selected integration is the official TCP Admin Network. It is external to the game simulation,
requires no patch or script, and supports polling structured company/date state. Task 6B is strictly
read-only: the adapter returns no actions and never sends chat, rcon, GameScript, or gameplay command
packets.

## Integration-path comparison

| Path | Versions and visibility | Latency/events/actions | Setup, portability, multiplayer | Maintenance, license, patch |
| --- | --- | --- | --- | --- |
| Admin Network | Versioned protocol; 15.3 protocol v3 exposes date, company identity/economy, fleet and facilities | TCP polling is low latency; protocol supports notifications and rcon, but 6B uses polls and no actions | Dedicated server plus admin config; cross-platform; designed for server administration, though this prototype enforces local-only | Official additive protocol; low-medium risk; OpenTTD GPL-2.0 installed separately; no patch |
| GameScript | Versioned API can see richer global/company state | Runs in game ticks with events and deity/company operations; JSON bridge still needed | Install/select a Squirrel script and carry it in saves; portable; server authoritative | Bridge and script become maintained/distributed components; GPL compatibility review; no OpenTTD patch |
| AI API | Versioned API with rich state for its company | Tick/event driven and action-capable | AI occupies and controls an AI company, not an arbitrary human company; portable | Maintained AI package and save dependency; no patch |
| Console/rcon | Supported console but output is command-specific text | Interactive; action-capable; not a structured state snapshot | Local console or Admin Network rcon; server/multiplayer implications | Commands/output can change and require parsers; no patch |
| Save parsing | Broad potential state but binary and offline | High/stale latency; no live events/actions | Requires save-file access; cross-version complexity; multiplayer snapshot only | High migration risk; format-coupled; no patch but likely OpenTTD-derived parsing work |
| Debug/developer output | Only configured diagnostics | Event-like text, incomplete state, no reliable actions | Debug launch configuration; platform-neutral text | Unstable/incomplete contract; no patch |
| Log/event output | Chat, console, command logs cover selected activity | Streaming; command logs are explicitly unstable and logging-only | Dedicated server configuration; multiplayer-sensitive | High semantic/version risk; no patch |
| Plugin or patched build | Arbitrary visibility possible | Depends on custom surface | Invasive build/install and weak portability | Highest maintenance/distribution burden; GPL obligations; patch required |
| Process memory | Potentially broad but undocumented | Fast, no supported events/actions | Platform/build-specific and unsafe in multiplayer | Extremely brittle; possible security/anti-cheat concerns; no source patch but invasive |
| Screen observation | Only visible UI state | Slow and lossy; input automation would be action-capable | GUI/display/accessibility dependent; unsuitable for headless servers | High localization/layout risk; no patch; explicitly excluded |

The Admin Network is the narrowest stable interface that validates the real adapter boundary. It is
not deterministic: OpenTTD can progress between polls, and another player/server process can change
state concurrently.

## Local setup on macOS

1. Download the official OpenTTD 15.3 macOS package from the
   [15.3 download page](https://www.openttd.org/downloads/openttd-releases/15.3), verify its published
   checksum, and place `OpenTTD.app` in `/Applications`.
2. Use OpenTTD's normal macOS profile at `$HOME/Documents/OpenTTD`. OpenTTD 15.3 stores ordinary
   settings in `openttd.cfg`, private bind lists in `private.cfg`, and secrets in `secrets.cfg`.
   A custom `-c` path does not relocate the companion files to the custom file's directory; when
   using `-c`, first change the working directory to the directory containing all three files.
3. Configure the following local-only values:

`openttd.cfg`:

```ini
[network]
server_admin_port = 3977
allow_insecure_admin_login = true
```

`private.cfg`:

```ini
[server_bind_addresses]
127.0.0.1 =
```

`secrets.cfg` (mode `0600`, never commit it):

```ini
[network]
admin_password = replace-with-a-local-secret
```

Launch a dedicated game or deterministic test save:

```bash
cd "$HOME/Documents/OpenTTD"
/Applications/OpenTTD.app/Contents/MacOS/openttd \
  -D 127.0.0.1:3979 \
  -g "$HOME/Documents/OpenTTD/save/sim-pilot-test.sav"
```

The `-g` value can be omitted to start a new game. The map generation seed is included in every
observation; Task 6B does not claim deterministic live execution or restore the test save.

On the validated development machine, the same profile contains mode-`0700` convenience scripts:

```bash
$HOME/Documents/OpenTTD/start-sim-pilot-server.sh
$HOME/Documents/OpenTTD/stop-sim-pilot-server.sh
source $HOME/Documents/OpenTTD/sim-pilot.env
```

The start script launches a detached loopback-only server with seed `12345` and creates a SimpleAI
company for observation. The environment file and `secrets.cfg` are mode `0600`.

Configure Sim Pilot in a separate shell:

```bash
export SIM_PILOT_OPENTTD_HOST=127.0.0.1
export SIM_PILOT_OPENTTD_PORT=3977
export SIM_PILOT_OPENTTD_ADMIN_PASSWORD=replace-with-a-local-secret
export SIM_PILOT_OPENTTD_COMPANY_ID=0
export SIM_PILOT_OPENTTD_VERSION=15.3
```

Then verify and observe:

```bash
uv run sim-pilot openttd doctor
uv run sim-pilot openttd capabilities
uv run sim-pilot openttd observe
uv run sim-pilot openttd watch --count 5
```

These commands are local/offline by default. They do not construct an Intent Compiler or Decision
Provider and do not read `OPENAI_API_KEY`. Later natural-language demos must still select
`--provider openai` explicitly.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SIM_PILOT_OPENTTD_HOST` | `127.0.0.1` | Must resolve exclusively to loopback in 6B |
| `SIM_PILOT_OPENTTD_PORT` | `3977` | Admin Network TCP port |
| `SIM_PILOT_OPENTTD_ADMIN_PASSWORD` | none | Required local admin password |
| `SIM_PILOT_OPENTTD_COMPANY_ID` | `0` | Company 0 through 14 |
| `SIM_PILOT_OPENTTD_VERSION` | `15.3` | Required application version |
| `SIM_PILOT_OPENTTD_CONNECTION_TIMEOUT_SECONDS` | `5` | Connect/authentication timeout |
| `SIM_PILOT_OPENTTD_OBSERVATION_TIMEOUT_SECONDS` | `5` | Per-state collection timeout |
| `SIM_PILOT_OPENTTD_POLL_INTERVAL_SECONDS` | `1` | Watch interval |
| `SIM_PILOT_OPENTTD_EXECUTABLE` | none | Optional doctor-only local path |
| `SIM_PILOT_OPENTTD_REQUIRED_SCRIPT` | none | Optional doctor path; no script is required by this method |
| `SIM_PILOT_OPENTTD_SAVE_PATH` | none | Optional local setup metadata; never restored by the adapter |

## State and resource contract

The serialized observation contains `game`, `resources`, and `adapter`. `game` is the exact typed
Admin Network projection. `adapter` identifies `openttd`, integration version `admin-network-v3`,
and these capabilities:

| Capability | Value |
| --- | --- |
| `read_state` | true |
| `execute_actions` | false |
| `supports_restore` | false |
| `supports_reconciliation` | false |
| `supports_pause` | false |
| `supports_events` | false (the protocol has notifications, but 6B does not expose them) |

Resource mapping uses OpenTTD internal base money units; scale is 1 and no configured display-
currency conversion is attempted.

| Resource | Source | Unit/scale/sign | Null behavior and summary |
| --- | --- | --- | --- |
| `cash` | `company.cash` | internal money, 1:1, signed | never null; `cash=` |
| `debt` / `loan` | `company.loan` | internal money, 1:1, non-negative | never null; `loan=` |
| `company_value` | last completed quarter value | internal money, 1:1, signed | never null; omitted from concise summary |
| `income` | unavailable as gross income | n/a | null; omitted |
| `expenses` | unavailable separately | n/a | null; omitted |
| `profit` | current-year net-income packet field | internal money, 1:1, signed | proxy, never null; `profit=` |
| `vehicle_count` | sum of five vehicle categories | vehicles, 1:1, non-negative | never null; `vehicles=` |
| `station_count` | sum of five station-facility categories | facilities, 1:1, non-negative | a multi-facility station can contribute more than once; `facilities=` |
| `date` | raw calendar-date packet | OpenTTD day plus formatted proleptic Gregorian date | never null; summary prefix and `Observation.tick` |

Sequence increases once per successful adapter observation. Timestamp is capture time in UTC.
`tick` is the raw calendar date and therefore may remain equal across successive observations.

Unsupported state includes paused/speed status, gross revenue, expenses, distinct profit, depots,
active/stopped/lost vehicles, vehicle profitability, route/order detail, towns, industries,
subsidies, alerts/news, and save identity. Recorded fixtures named for paused and stopped-vehicle
scenarios explicitly mark those fields unavailable instead of fabricating values.

## Persistence and recovery

Canonical observations and adapter metadata serialize through the existing event repository.
They are evidence snapshots, not `SimulationCheckpoint` restoration data. A resumed OpenTTD task
must create a new client, reconnect, observe fresh state, and compare it to the last persisted
observation. Authoritative restoration and crash-window reconciliation remain future work.

## Tests and troubleshooting

Fixture tests require no game or credentials:

```bash
uv run pytest tests/openttd
```

Live read-only acceptance is explicit:

```bash
SIM_PILOT_LIVE_OPENTTD=1 uv run pytest -m live tests/openttd/test_live_openttd.py -s
```

Common failures:

- Connection refused: launch a dedicated server, configure an admin password, and check port 3977.
- Admin error 6/not authorized: enable insecure admin login only on the loopback development server.
- Unsupported version/protocol: install exactly OpenTTD 15.3; do not override validation.
- Missing company: inspect the game and select an existing company ID.
- Timeout: ensure the game is running and the selected company exists; then increase the observation
  timeout if local load is unusually high.

The development machine was subsequently validated against the official OpenTTD 15.3 macOS
application on 2026-07-16. A disposable loopback-only dedicated server using map seed `12345` and a
SimpleAI company passed `doctor`, one structured CLI observation, a bounded two-observation watch,
clean shutdown, and the opt-in live pytest acceptance test. The first captured live observation was
game date `1950-01-06`, company `0`, cash `93993`, loan `100000`, current-year net income `-6007`,
zero vehicles, and two station facilities. Protocol, adapter, CLI, persistence, and failure paths
also remain covered by deterministic sanitized fixtures and a local fake TCP server.

## Future write path

The Admin Network supports remote console commands, and a GameScript can exchange JSON through the
Admin Port. Task 6C must select actions only after verifying the current 15.3 interface, preconditions,
and independently observable postconditions. Route construction, vehicle purchasing, broad company
control, screen automation, and unstable command-log replay are not implied by this adapter.
