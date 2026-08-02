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

### Read-only gameplay analysis

`sim-pilot ask` and `sim-pilot openttd analyze` accept a selected `--snapshot FILE`. Without one,
they probe the live bridge identity and reuse a compatible snapshot up to five seconds old, or
perform a fresh read-only collection when reuse is unsafe. `--live`, `--fresh`, and
`--max-snapshot-age 0` force a complete collection; `--max-snapshot-age SECONDS` sets a stricter
caller freshness policy within the 30-second cache ceiling.

```bash
uv run sim-pilot ask "Which vehicle lost the most money last year?"
uv run sim-pilot ask --snapshot snapshot.json --detailed "How healthy is the company?"
uv run sim-pilot ask --max-snapshot-age 2 "Which station has the most waiting cargo?"
uv run sim-pilot openttd analyze vehicles --fresh --top 10
```

Compact output is default. `--detailed` exposes snapshot identity and freshness; `--json` emits the
canonical response; `ask --evidence` expands evidence in the compact response. Compiler and
explanation providers independently default to `none`; selecting `codex` or `openai` never enables
OpenTTD writes.

Each supported answer is retained under `SIM_PILOT_ANALYSIS_SESSION_DIRECTORY` for explicit local
drill-down and compatible contextual follow-ups:

```bash
uv run sim-pilot analysis show
uv run sim-pilot analysis evidence ANALYSIS_ID FINDING_ID
uv run sim-pilot analysis entity ANALYSIS_ID vehicle VEHICLE_ID
uv run sim-pilot analysis inspect ANALYSIS_ID FINDING_ID
```

`analysis inspect` performs a fresh identity/entity validation but currently returns `unsupported`:
the proven OpenTTD 15.3 bridge cannot read a client viewport or verify that a named entity was
opened. See [014-gameplay-analysis-engine.md](014-gameplay-analysis-engine.md), the
[intelligence guide](016-openttd-intelligence-guide.md), and the
[Phase 10A capability decision](022-phase10a-named-entity-inspection.md).

## Rail Route 2.3.24

The existing `rail-route status`, `do`, and `play` commands remain the macOS screen-control path.
The semantic bridge is an independent, explicitly installed read-only path. UI mutation is a
separate capability:

```bash
sh rail_route_bridge/scripts/test.sh

# Requires a checksum-verified BepInEx 5.4.23.5 extraction and the exact local game assemblies.
BEPINEX_ROOT=/path/to/BepInEx \
RAIL_ROUTE_MANAGED_PATH="/path/to/Rail Route_Data/Managed" \
  sh rail_route_bridge/scripts/build-plugin.sh

uv run sim-pilot rail-route bridge doctor
uv run sim-pilot rail-route bridge install
uv run sim-pilot rail-route bridge verify
uv run sim-pilot rail-route bridge capabilities
uv run sim-pilot rail-route bridge observe --json
uv run sim-pilot rail-route bridge list trains
uv run sim-pilot rail-route bridge list stations
uv run sim-pilot rail-route bridge list incoming-traffic
uv run sim-pilot rail-route bridge list track-occupancy
uv run sim-pilot rail-route bridge show trains <UUID-or-reporting-number>
uv run sim-pilot rail-route bridge prove-read-only
uv run sim-pilot rail-route ui doctor
uv run sim-pilot rail-route ui observe
uv run sim-pilot rail-route do "set a route from SIG-W-IN to SIG-C-W" --dry-run
uv run sim-pilot rail-route do "set a route from SIG-W-IN to SIG-C-W"
```

Run `set_route_ui` only in the paused canonical Test Yard with Construction and overlays closed. It
brackets screenshots with semantic observations, sends one click per cycle, and verifies the final
allocation. It does not retry or cancel the route. Owner-only evidence is appended to
`~/Library/Application Support/Sim Pilot/rail-route-ui/traces.jsonl`; screenshot pixels are not
stored.

`doctor` and installation require Rail Route to be closed. They validate the exact app, Steam build,
Unity/Mono runtime, executable/assembly hashes, universal architectures, plugin artifact, symlinks,
and target collisions. Installation fetches only the pinned BepInEx archive, verifies its SHA-256,
and records every owned file. It does not change the app bundle or Steam launch configuration.

Launch through the temporary, explicit Steam `%command%` wrapper documented in
[025-rail-route-semantic-bridge.md](025-rail-route-semantic-bridge.md). The installer never changes
Steam configuration; the operator must add and later remove that option visibly. The first live
proof must use x86_64/Rosetta because that is the observed baseline. Start bridge runs from Steam's
Library Play button; Dock, Finder, and Spotlight launches bypass the Steam launch option.

Recovery is deliberately conservative:

```bash
uv run sim-pilot rail-route bridge disable
uv run sim-pilot rail-route bridge uninstall
```

Disable moves only the owned plugin. Uninstall refuses a changed owned file and preserves generated
or unknown files for review. It removes the owner-only authentication token. The 2026-07-21 live
recovery removed all 23 unchanged manifest-owned files, preserved generated logs/config/cache, and
returned to an ordinary Steam launch with no bridge listener. The installer never edits Steam
configuration, so the operator must clear the temporary launch option explicitly.

## Frozen Software Inc. reference capability

The Software Inc. roadmap is frozen. The retained commands remain available for maintenance,
reproduction, and bounded use inside their documented evidence; they do not authorize a new
Software Inc. milestone. Prompt 1 is discovery-only. It registers no gameplay actions and does not
compose a Software Inc. task runtime:

```bash
uv run sim-pilot software-inc doctor
uv run sim-pilot software-inc doctor --json
uv run sim-pilot software-inc capabilities
uv run sim-pilot software-inc probe doctor
```

Close Software Inc. before changing official mod files:

```bash
uv run sim-pilot software-inc probe install
uv run sim-pilot software-inc probe verify
uv run sim-pilot software-inc probe disable
uv run sim-pilot software-inc probe uninstall
```

Install and recovery touch only the checksum-recorded source probe and its owner-only Sim Pilot
manifest. `verify` confirms ownership, least authority, enablement, and any available lifecycle-log
evidence. It does not claim that employee, team, project, product, office, or finance state is
observable. See [027-software-inc-foundation.md](027-software-inc-foundation.md).

After the first install, launch Software Inc., open **Mods → Code mods**, and toggle
`SimPilotDiscoveryProbe` on. This is an explicit one-time game-owned activation step. Re-run
`software-inc probe doctor`; `loaded: true` and an `activated` lifecycle event are the required
live proof. If Software Inc. opens behind Steam, bring its window to the foreground because this
build has `RunInBackground` disabled during startup.

### Guided terminal

The teacher and advisor paths are read-only and require no model provider:

```bash
uv run sim-pilot software-inc ask "What do teams do?"
uv run sim-pilot software-inc ask "How many employees do I have?" --json
uv run sim-pilot software-inc crash-course
uv run sim-pilot software-inc crash-course hiring
uv run sim-pilot software-inc crash-course office
uv run sim-pilot software-inc crash-course schedules
uv run sim-pilot software-inc crash-course roles
uv run sim-pilot software-inc crash-course servers
uv run sim-pilot software-inc crash-course training
uv run sim-pilot software-inc crash-course --testing
uv run sim-pilot software-inc recommend
uv run sim-pilot software-inc capabilities --json
uv run sim-pilot software-inc play
```

The default crash course uses checked-in knowledge if no live company is available and labels the
missing personalization. Testing mode reports exact game/build, bridge and artifact identity,
current save/session, semantic action count, live versus offline UI evidence, and known blockers.

Inside `play`, `/recommend` stores one process-local current recommendation and `/why` explains it.
`/operate use your recommended plan` rechecks expiration, save/session, capability fingerprint,
and current capability compatibility before delegation. Questions, courses, status,
recommendations, explanations, and ambiguous messages cannot call the UI executor.

Only explicit delegation can send input. The Guided Operator currently permits `pause`, `resume`,
and `open_manage_teams` when all live gates pass. It rejects Phase 4 staffing because that catalog
is offline-tested but not live-promoted. Use
[031-software-inc-guided-operator-and-game-knowledge.md](031-software-inc-guided-operator-and-game-knowledge.md)
for evidence rules and the exact boundary.

### Read-only bridge and verified UI control

With the separately approved bridge enabled and a disposable company loaded:

```bash
uv run sim-pilot software-inc bridge capabilities
uv run sim-pilot software-inc bridge observe
uv run sim-pilot software-inc ui doctor
uv run sim-pilot software-inc ui observe
uv run sim-pilot software-inc ui capabilities
```

The UI observer foregrounds the already-running exact PID, captures its unique CoreGraphics game
window, and brackets the frame with read-only semantic snapshots. Signed coordinates and all active
displays are supported. If the existing window is partly offscreen or crosses displays, the observer
moves it once to fit the primary display and verifies the same PID/window before capture. It does
not resize, launch, or restart the game. Observation and dry-run commands send no gameplay input.
Foreground activation uses AppKit against the exact existing Software Inc. bundle and verifies the
resulting frontmost PID; Terminal does not need Automation permission to control System Events for
this step. Full-screen Space transitions receive a bounded one-second exact-window settling period
before capture or input; stale frames still fail closed.
If the window is larger than the primary display, select a fitting in-game resolution or fullscreen
mode and retry.

```bash
uv run sim-pilot software-inc ui do "pause the game"
uv run sim-pilot software-inc ui do "resume the game"
uv run sim-pilot software-inc ui do "open manage teams" --dry-run
uv run sim-pilot software-inc ui do "open manage teams"
uv run sim-pilot software-inc ui do "create a team named Support Alpha"
uv run sim-pilot software-inc ui do \
  "observe programmer applicants for Support Alpha under $8,000 per month"
uv run sim-pilot software-inc ui do \
  "hire one programmer for Support Alpha for no more than $8,000 per month"
uv run sim-pilot software-inc office readiness Core
uv run sim-pilot software-inc ask "Does Core have enough desks?"
uv run sim-pilot software-inc ask "What hours does Core work?"
uv run sim-pilot software-inc ui do "set Core working hours to 8-16" --dry-run
uv run sim-pilot software-inc ui do "assign Gage Chen as Programmer for Core" --dry-run
uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve" --dry-run
uv run sim-pilot software-inc ui do \
  "prepare one workstation for Core while keeping $49,000 in reserve"
uv run sim-pilot software-inc contracts do "browse contracts"
uv run sim-pilot software-inc contracts do \
  "find a small contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts do \
  "accept the recommended contract for Core with reward at least $10,000 while keeping $50,000 in reserve"
uv run sim-pilot software-inc contracts status
uv run sim-pilot software-inc contracts do "advance the current contract" --seconds 10
uv run sim-pilot software-inc contracts do "review the current contract"
uv run sim-pilot software-inc contracts do "promote the current contract"
uv run sim-pilot software-inc contracts do "release the current contract"
uv run sim-pilot software-inc training do \
  "recommend one suitable employee from Core for System design education while keeping $50,000 in cash"
uv run sim-pilot software-inc training do \
  "train one suitable employee from Core in System design for three months while keeping $50,000 in cash"
uv run sim-pilot software-inc training status
uv run sim-pilot software-inc training do "advance training" --seconds 10
uv run sim-pilot software-inc crash-course products
uv run sim-pilot software-inc crash-course development
uv run sim-pilot software-inc products types
uv run sim-pilot software-inc products features --type "Game Engine"
uv run sim-pilot software-inc products operating-systems
uv run sim-pilot software-inc products recommend --minimum-cash-reserve 50000
uv run sim-pilot software-inc products start --minimum-cash-reserve 50000 --dry-run
uv run sim-pilot software-inc products do \
  "begin a small game engine called Atlas using Core and keep $50,000 in reserve"
uv run sim-pilot software-inc products status
uv run sim-pilot software-inc products do "advance Atlas" --seconds 10
uv run sim-pilot software-inc products do "review Atlas"
uv run sim-pilot software-inc products do "iterate Atlas"
uv run sim-pilot software-inc products do "promote Atlas"
uv run sim-pilot software-inc products do "hold Atlas"
uv run sim-pilot software-inc products do "resume Atlas"
```

Use a disposable company. Every cycle sends zero or one gesture. If a sent gesture cannot be
verified, do not repeat it until the resulting screen is inspected. Unknown scenes, blocking
modals, changed windows, and stale targets stop before further input. The bridge action catalog
remains empty. Owner-only traces under
`~/Library/Application Support/Sim Pilot/software-inc/ui/traces.jsonl` contain no screenshot
pixels, and UI control does not touch saves or installed bridge bytes.

Team creation, paid applicant search, and final hire each form an exact approval-bound plan.
Hiring can therefore prompt twice: the first prompt authorizes only the visible one-time search
charge; the second names the exact applicant, target team, observed monthly salary, and user cap.
Declining either prompt sends no commitment click. Staffing traces are stored separately at
`~/Library/Application Support/Sim Pilot/software-inc/ui/staffing-traces.jsonl`.

Schedule, role, and workstation workflows use the same owner-only staffing trace and
one-gesture/re-observe contract. The workstation command first reuses suitable existing capacity,
then prints an exact itemized plan and asks default-no approval. It can assign only an empty room,
select exact visible catalog controls, and click placement only after first moving to a fresh
room/snap target and then observing a green preview for the approved item, price, and room. It
verifies every component and exact cumulative cash before continuing. Existing valid capacity
completes with zero approval, gestures, or duplicate spending. Furniture relocation/sale,
occupied-room reassignment, employee desk ownership, construction, and server creation remain
unavailable. See
[032-software-inc-office-readiness.md](032-software-inc-office-readiness.md) and
[033-software-inc-workstation-placement.md](033-software-inc-workstation-placement.md).

Contract recommendation opens and completely observes the visible market before applying exact
team, role, workspace, active-work, reward, deadline, and full-penalty reserve rules. The contract
workflow is owner-only and resumable. Each economic or irreversible commitment has its own
default-no approval; one approval cannot authorize later review, promotion, deadline risk, or
release. See [034-software-inc-first-contract.md](034-software-inc-first-contract.md).

Training recommendation requires complete employee, team, work-item, Education, and finance
observations. It reports exact direct cost, continuing payroll, temporary capacity, reserve, and
unknown productivity benefit. The final Education click has one default-no exact approval. Every
advance interval is capped at 30 real seconds and uses interruption-safe cleanup to finish paused;
repeat it until the exact course disappears and System level increases. Duplicate starts and
completed advances reconcile with zero input. See
[035-software-inc-first-training-assignment.md](035-software-inc-first-training-assignment.md).

Atlas recommendation requires the visible current-version design configuration, unlocked Game
Engine catalog evidence, exact Core assignment, observed Programmer and Designer skill, selected
features and operating systems, no unresolved team warning or unsupported server requirement, and
a conservative payroll/infrastructure projection above the reserve. `start --dry-run` sends no
input from paused gameplay. A live start may perform reversible setup, then prints one exact
default-no creation approval. Every review, iteration, and stage promotion has a separate approval.
`advance` runs at most 30 real seconds and guarantees pause; repeat bounded cycles as needed. Prompt
7 stops at verified Beta and never releases Atlas. See
[036-software-inc-first-product-atlas.md](036-software-inc-first-product-atlas.md).

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
| 24 | Rail Route discovery, bridge, observation, or action failure |
| 25 | Software Inc. discovery or official-probe lifecycle failure |

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
