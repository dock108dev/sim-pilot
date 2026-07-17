# OpenTTD 15.3 GameScript Capability Discovery

## 1. Executive conclusion

**Decision: constrained go.** OpenTTD 15.3 has an official, working,
bidirectional JSON channel between Admin Network clients and the one active
GameScript. GameScript supplies much richer structured state than the Admin
Network and `GSCompanyMode` can select any existing company without testing
whether it is AI-controlled. Commands in that scope use the selected company's
funds and normal command validation.

Task 7A did not, however, execute infrastructure construction in a human-created
company. The live disposable server had company 0 created by SimpleAI. It proved
company-context entry, state reads, `GSTestMode`, reversible mutation,
independent restoration, save/load, client reconnect, and server restart. Source
proves that the same company-mode path has no human/AI branch, but autonomous
construction remains outside the verified production capability catalog.

Task 7B should therefore implement telemetry, capability negotiation, recovery,
and the narrow verified command substrate. It must not advertise construction or
vehicle management until a disposable human-company construction probe passes.

Task 7B implemented that constrained decision as protocol v1: periodic
heartbeat, full snapshots, resynchronization, saved identity and command ledger,
and the sole verified `set_company_name` action. State deltas and generic events
were not productionized because Task 7A did not verify them. Production API
validation also revised the proposed human/AI GameScript field: API 15 does not
provide the supported getter assumed during discovery, so the combined adapter
uses Admin Network as the only authority for human/AI status. See
`docs/005-openttd-bridge-protocol.md`.

## 2. Tested versions and primary evidence

- OpenTTD 15.3, exact tag commit `14ec60f248547d4d062a1160f0fc26d742319888`.
- Admin Network protocol 3, advertised by the running server.
- GameScript API `15`; `src/game/game_info.hpp`, `ApiVersions`.
- Squirrel `2.2.5 stable - With custom OpenTTD modifications`;
  `src/3rdparty/squirrel/include/squirrel.h`, `SQUIRREL_VERSION`.
- Sim Pilot baseline commit `0f0f8e6` (Task 6C).

All source paths below are relative to the OpenTTD 15.3 tree at that commit.
Generated master documentation was used only for candidate discovery.

Material source evidence:

| Conclusion | OpenTTD 15.3 source |
|---|---|
| Server-only singleton GameScript | `src/game/game_core.cpp`, `Game::GameLoop`, `Game::StartNew`; `src/game/game.hpp`, `Game::instance` |
| Save/load and missing-script behavior | `src/saveload/game_sl.cpp`, `Save_GSDT`, `Load_GSDT`; `src/game/game_instance.cpp` |
| Arbitrary temporary company context | `src/script/api/script_companymode.hpp/.cpp`, `ScriptCompanyMode` |
| Test-only commands and accounting | `src/script/api/script_testmode.hpp`; `script_accounting.hpp` |
| GameScript to Admin | `src/script/api/script_admin.hpp/.cpp`, `ScriptAdmin::Send`; `src/network/network_admin.cpp`, `NetworkAdminGameScript` |
| Admin to GameScript | `src/network/network_admin.cpp`, `ServerNetworkAdminSocketHandler::Receive_ADMIN_GAMESCRIPT`; `src/script/api/script_event_types.cpp`, `ScriptEventAdminPort` |
| Packet numbers and subscription | `src/network/core/tcp_admin.h`, `ADMIN_PACKET_ADMIN_GAMESCRIPT`, `ADMIN_PACKET_SERVER_GAMESCRIPT`, `ADMIN_UPDATE_GAMESCRIPT` |
| Payload limits | `src/network/core/config.h`, `NETWORK_GAMESCRIPT_JSON_LENGTH`; `src/script/api/script_admin.cpp` |

## 3. Execution model

OpenTTD loads at most one configured GameScript. `Game::GameLoop` runs it on the
server (including local single-player's server side), never on a multiplayer
client. The controller starts in deity context, calls `Start()`, and advances
cooperatively through `Sleep(ticks)`. A runaway or failed script is suspended by
the scripting framework; it does not become a client-side worker.

The selected script is the first entry in `[game_scripts]`. A package consists
of `info.nut` and `main.nut` under an OpenTTD `game/<package>` directory. The
probe declares API 15. Settings are declared by `GSInfo.GetSettings()` and read
through `GSController.GetSetting()`.

`Save()` returns only supported Squirrel scalar/array/table data. On load,
OpenTTD constructs the instance, calls `Load(version, data)`, then `Start()`.
Save/load callbacks must not issue game-changing commands. Pending events are
not serialized; durable command IDs and a resynchronization handshake are
therefore required. Script identity, version, settings, and returned state are
stored in the save. If the named script is absent, OpenTTD logs the condition
and continues without a GameScript; consumers must detect heartbeat loss.

Dedicated and multiplayer execution is authoritative on the server. A new game
or load changes the script-instance boundary even when the process remains up.

## 4. Company authority

| Context | `COMPANY_SELF` / authority | Finding |
|---|---|---|
| Initial/deity | invalid company / `OWNER_DEITY` | World and GameScript UI APIs; company-only commands fail. |
| `GSCompanyMode(id)` | resolved selected ID | Temporary until object destruction; all queries and commands run as that company. |
| Invalid/spectator | invalid | `GSCompanyMode.IsValid()` false; company command returns invalid-company error. |
| Existing human company | selected human ID | **Source-proven supported.** Resolution checks only existence; there is no `is_ai` rejection. Not live-probed in 7A. |
| Existing AI company | selected AI ID | Source- and live-proven for company 0. |
| Dedicated server | server singleton | Live-proven. |
| Local single player | local server singleton | Source-proven; not separately live-probed. |
| Multiplayer client | none | GameScript loop does not run there. |

`ScriptCompanyMode` explicitly states that actions execute as if the real player
issued them, costs are charged to that company, and insufficient funds abort.
Its implementation resolves only `COMPANY_SELF`/existence, stores the previous
company, sets the selected company, and restores the previous value in its
destructor. Human-company authority is therefore a definitive **yes at the
command-dispatch boundary**, but construction coverage remains capability-gated
until its live probe is completed.

## 5. State visibility matrix

Classifications: **A** available, **D** derived, **P** partial, **C** requires
company/deity context, **E** event-only, **U** unsupported, **V** unverified live.
Invalid IDs generally trigger documented precondition errors or return an
invalid sentinel/`null`; callers must validate list membership first. Large map
and entity scans are O(tiles/entities), must be budgeted across ticks, and
should use deltas plus periodic snapshots.

| Resource / every requested field | Class | API 15 evidence and notes | Probe |
|---|---:|---|---|
| Calendar date | A | `GSDate.GetCurrentDate()`; integer day | live in envelopes |
| Economy date | P | Economy/calendar separation is exposed through time APIs/settings, but no stable speed clock contract was proven | source |
| Pause state | A | `GSGame.IsPaused()` | source |
| Game speed | U | No GameScript API for client/server speed setting | source search |
| Map dimensions; tile coordinates | A | `GSMap.GetMapSizeX/Y`, `GetTileIndex`, `GetTileX/Y` | source |
| Game settings | P | `GSGameSettings.GetValue`; only script-exposed settings, invalid name errors | source |
| Loaded NewGRFs | P | `GSNewGRF` parameter/name access; not a complete content manifest | source |
| Cargo types; vehicle engines; road/rail/infrastructure types | A | cargo/engine/road/rail lists and `GSCargo`, `GSEngine`, `GSRoad`, `GSRail` | source |
| Company IDs, names, human/AI, inactive/bankruptcy | A | `GSCompanyList`, `GetName`, `IsHuman`, `IsAI`; list membership; bankruptcy partly events | live name; rest source |
| Bank balance | A | `GSCompany.GetBankBalance(id)`; signed money | live |
| Loan | C | `GSCompany.GetLoanAmount()` in selected company | live |
| Maximum loan | P | game setting plus loan rules; derive current limit, may change over time | source |
| Company value; quarterly income, expenses, rating, cargo delivered | A | `GetQuarterlyCompanyValue/Income/Expenses/PerformanceRating/CargoDelivered` | source |
| Infrastructure counts | A | `GSInfrastructure.GetInfrastructurePieceCount` | source |
| Headquarters | A | `GSCompany.GetCompanyHQ` | source |
| Auto-renew status/months/money | A | `GSCompany.GetAutoRenew*` | source |
| Livery | U | No GameScript livery read API | source search |
| Vehicle IDs/type/owner/engine/age/reliability/speed/location | A | `GSVehicleList`, `GSVehicle.GetVehicleType/GetOwner/GetEngineType/GetAge/GetReliability/GetCurrentSpeed/GetLocation` | source |
| Vehicle status/stopped/depot/breakdown | P | `IsStoppedInDepot`, `IsInDepot`, events; no complete status enum or persistent breakdown flag | source |
| Vehicle profit/running cost | A | `GetProfitThisYear/LastYear`, `GetRunningCost` | source |
| Vehicle cargo/capacity | P | cargo type/load/capacity APIs; articulated consist aggregation required | source |
| Vehicle orders/group/destination | A/D | `GSOrder` iteration, `GetGroupID`; destination derived from current order | source |
| Station IDs/owner/location/facilities | A | station lists, `GSBaseStation.GetOwner/GetLocation`, `GSStation.HasStationType` | source |
| Station accepted/waiting cargo/ratings | A | `GSStation.GetCargoAcceptance/GetCargoWaiting/GetCargoRating` | source |
| Station served vehicles/catchment/nearby town | D/P | derive from orders, tiles, and distances; exact GUI catchment overlay not exposed | source |
| Depot locations | D | scan depot tiles/types; potentially expensive | source |
| Town IDs/names/coordinates/population/house count/growth | A | `GSTownList`, `GetName/GetLocation/GetPopulation/GetHouseCount/GetGrowthRate` | source |
| Town ratings by company | A | `GSTown.GetRating` | source |
| Town transported percentages; production/acceptance indicators | A/P | last-month production/supplied/transport percentage; acceptance derived from cargo/tile APIs | source |
| Town road layout; authority restrictions | P | setting and tile derivation; no complete per-town policy object | source |
| Industry IDs/type/name/location | A | `GSIndustryList`, `GetIndustryType/GetName/GetLocation` | source |
| Industry production/transported/accepted/produced cargo | A | last-month and cargo APIs | source |
| Industry nearby stations | D | distance/station scan | source |
| Industry closure/construction state | E/P | open/close events and list snapshots; transient construction state absent | source |
| Road/rail/station tiles, bridges, tunnels, signals | A | tile-type and transport-specific APIs | source |
| Terrain height/slope/water/ownership/buildability | A/P | `GSTile` getters; buildability is command/context-specific | source |
| Path connectivity/route distance | D/P | local connection and distance APIs; no universal pathfinder | source |
| Estimated construction cost | C | `GSTestMode` + `GSAccounting`; exact only for a concrete command sequence | live for name (zero); construction V |
| Vehicle crash | E | vehicle-crashed event | source |
| Vehicle breakdown | E/P | breakdown event; no durable active-state field | source |
| Company bankruptcy/creation | E/A | company events plus company-list snapshots | source |
| Industry opening/closing | E | industry events | source |
| Town growth | D | compare snapshots; no dedicated growth event | source |
| Subsidy creation/expiry | E/A | subsidy events and lists | source |
| Goal completion | E/A | goal event/state | source |
| Engine availability | E/A | engine-available event and engine list | source |
| Administrative messages | E | `GSEventAdminPort` JSON objects | live |
| Other GameScript events | E | `GSEvent` typed subclasses | source |

### Admin Network comparison and combined observation

Admin Network and GameScript both expose date, company identity/name/AI flag,
cash/loan, quarterly economy, performance, cargo totals, and aggregate vehicle
and station counts. They should match after allowing for packet cadence. Admin
money is serialized integer money; GameScript uses `Money`. Any disagreement is
resolved by a fresh Admin poll for lifecycle/economy and a GameScript full
snapshot for entity/map detail, with both source timestamps retained.

Admin-only material data: connection/server metadata, network clients, protocol
health, and authoritative server/new-game/shutdown notifications. GameScript-only
material data: entity IDs and attributes, towns, industries, cargo/engine types,
orders, tiles, events, settings, and command errors/test costs.

Proposed (not implemented) observation: `{admin_metadata, game_date,
company_summary, entities, towns, industries, map_summary, events,
bridge_health, source_sequences, captured_at}`. Full map data should be paged or
queried, not embedded in every observation.

## 6. Action authority matrix

Legend: **C** company mode, **D** deity, **U** unavailable, **V** API/source
verified but live action unverified. Unless noted, company commands spend company
funds, use normal rules, return `bool` plus `GSController.GetLastError()`, can be
costed through `GSTestMode`/`GSAccounting`, and are independently observable.

| Requested actions | Authority | API family | Recovery / live result |
|---|---:|---|---|
| Set company name | C | `GSCompany.SetName` | state-comparable, compensatable; **live changed and restored** |
| Change loan | C | `SetLoanAmount`, `SetMinimumLoanAmount` | state-comparable; V |
| Change bank balance | D | `ChangeBankBalance` | deity accounting operation, not normal company spend; V |
| Build headquarters | C | `GSCompany.BuildCompanyHQ` | tile-observable; V |
| Auto-renew configuration | C | `SetAutoRenewStatus/Months/Money` | state-comparable and reversible; V |
| Livery changes | U | none | unsupported |
| Build/sell/clone/refit/start-stop/send vehicle to depot | C | `GSVehicle` | rule-bound; IDs/funds observable; V |
| Create/modify orders; assign group; service interval; replacement | C | `GSOrder`, `GSGroup`, `GSVehicle`, `GSGroup.SetAutoReplace` | state-comparable, some multi-command ambiguity; V |
| Build/remove road, road stop, depot, bridge, tunnel; road type | C | `GSRoad`, `GSBridge`, `GSTunnel` | normally reversible; **construction live probe pending** |
| Build/remove rail, station, depot, signal, bridge, tunnel; rail type | C | `GSRail`, bridge/tunnel APIs | normally reversible; V |
| Airports, docks, canals, locks, buoys, ship depots, hangars | C | `GSAirport`, `GSMarine`, station/vehicle APIs | topology/rule-bound; V |
| Terraform; clear tile | C | `GSTile` | costly/destructive; unsafe autonomous retry; V |
| Create industry/town; alter rating; create subsidy | D | `GSIndustryType`, `GSTown`, `GSSubsidy` | world mutation, not company construction; V |
| Fund town | C | `GSTown.PerformTownAction` | spends company funds; V |
| Goals, story pages, news | D | `GSGoal`, `GSStoryPage`, `GSNews` | GameScript-owned UI/state; V |
| Create/remove signs | C/D depending owner | `GSSign` | compensatable; V |

Identifiers are save-local and must never be assumed stable across new games.
Most create operations return an ID only after command completion. Destructive or
multi-command operations are unsafe for blind retry; reconcile by command ID and
fresh state. `GSTestMode` prevents command execution and checks capability,
rules, and funds; `GSAccounting.GetCosts()` totals the attempted command block.
The live name probe returned success, cost 0, and no test-mode state change.

## 7. Communication matrix

| Path | Status | Exact mechanism |
|---|---|---|
| GameScript → Admin | Official, live-proven | `GSAdmin.Send(table)` → packet 124 `SERVER_GAMESCRIPT`; broadcast to active clients subscribed to update type 9 automatic |
| Admin → GameScript | Official, live-proven | packet 6 `ADMIN_GAMESCRIPT` containing NUL-terminated JSON object → `GSEventAdminPort` |
| RCON | Official but unnecessary for bridge commands | Admin packet 5; useful for disposable setup/save/load only |
| Script settings | startup/restart configuration | not an interactive command channel |
| Goals/story/signs/chat | one-way in-game UI or indirect | unsuitable for durable automation |
| Files/local IPC | unsupported sandbox escape | unavailable without patch/unsafe workarounds |
| Patched network extension | possible, requires fork | rejected for Task 7B |

JSON supports null, boolean, integer, string, array, and object. Floats and a
non-object inbound root are rejected. Encoding is UTF-8 in a NUL-terminated
Admin protocol string. Admin→GameScript permits 8,999 payload bytes
(`NETWORK_GAMESCRIPT_JSON_LENGTH` includes NUL). `GSAdmin.Send` rejects output
over 1,450 bytes. There is no built-in correlation, persistence, delivery ACK,
or queue when no admin is connected; the bridge envelope supplies those.
Per-connection TCP preserves packet order. GameScript output is broadcast to all
subscribed admins, so clients must filter instance and correlation IDs.

## 8. Measured communication and probe results

Conditions: macOS, OpenTTD 15.3 dedicated server on `127.0.0.1:3977`, fixed
generation seed, disposable profile/save, API 15 probe script, local Admin client.

| Probe | Result | Evidence |
|---|---|---|
| Startup/heartbeat | passed | startup hello plus periodic heartbeat observed |
| GS→Admin JSON | passed | typed hello/capabilities/response packets |
| Admin→GS JSON | passed | hello request and pings received/responded |
| Ordering | passed | monotonically increasing sequence in TCP receive order |
| Latency | passed | first 5-ping run: min 8.35 ms, median 25.34 ms, max 48.23 ms; later run max 80.90 ms |
| Unsupported command | passed | deterministic `unsupported_command` rejection |
| Duplicate command | passed | first completed, second `duplicate_request`; IDs survived client reconnect |
| Client restart/reconnect | passed | new client resynchronized with hello request |
| Company context/read | passed on AI company 0 | valid mode, name, cash 99,220 in final run, loan 100,000 |
| Test mode | passed for name command | accepted, cost zero, state unchanged |
| Reversible mutation | passed on AI company 0 | temporary name changed and original `Narnbury Transport` restored |
| Save/load | passed | `loaded:true`, sequence continued from saved value |
| OpenTTD process restart | passed | saved instance state restored and bridge resynchronized |
| Human company runtime | inconclusive environment | no human company existed; source boundary is definitive yes |
| Construction/cost/removal/persistence | not yet supported | deferred capability gate for 7B |
| Payload limit/malformed JSON | source + offline tests | boundary validation passed; destructive live flooding not run |

Raw sanitized samples belong in `discovery/openttd_gamescript/results/`. TCP did
not duplicate or drop any tested packet. The protocol cannot promise delivery
during disconnect; reconnect always requires a full resynchronization.

## 9. Architecture options

Weights: human-company control 25, write coverage 20, read coverage 15,
recovery/verification 15, installation 10, security 5, maintenance/update 10.
Scores are 1–5; weighted total is out of 500.

| Option | Human | Write | Read | Recovery | Install | Security | Maintain | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A. One-way GS telemetry + RCON | 1 | 1 | 5 | 3 | 4 | 3 | 4 | 275 |
| B. Bidirectional GameScript | 4 | 4 | 5 | 4 | 3 | 4 | 4 | **405** |
| C. GS plus in-game AI company | 1 | 4 | 5 | 4 | 2 | 4 | 3 | 315 |
| D. NoAI controller | 1 | 5 | 5 | 4 | 2 | 4 | 3 | 335 |
| E. OpenTTD fork/patch | 5 | 5 | 5 | 5 | 1 | 3 | 1 | 420 |
| F. GS telemetry + UI input | 5 | 3 | 5 | 1 | 3 | 1 | 2 | 325 |

Option E scores high functionally but is rejected due to distribution,
maintenance, version, and GPL fork obligations. NoAI has excellent authority for
its own company but cannot coexist as controller of a human player's company.
UI control is fragile and excluded. Option B is the selected product direction,
constrained to capabilities actually negotiated and live-verified.

## 10. Recommended design and Task 7B layout

```text
src/sim_pilot/openttd/
  admin/                 # existing wire transport split out over time
  gamescript/
    protocol.py          # envelope/version and strict validation
    messages.py          # typed payloads
    client.py            # subscription, correlation, resync
    errors.py
  models/
src/sim_pilot/adapters/openttd/
  adapter.py
  capabilities.py
  verification.py
  reconciliation.py
openttd_gamescript/sim_pilot_bridge/
  info.nut
  main.nut
  protocol.nut
  snapshots.nut
  commands.nut
```

The transport knows Admin packets, not runtime lifecycle. The adapter consumes
domain models and negotiated capabilities. The OpenTTD-side package remains an
independently versioned server component.

## 11. Proposed bridge protocol v1

Envelope fields are: `protocol_version` (integer 1), monotonic `sequence`,
stable `message_id`, optional `correlation_id`, `script_instance_id`,
`message_type`, integer `game_date`, optional `company_id`, and object `payload`.
Task 7B also adds payload fields for `openttd_version`, `gamescript_api_version`,
`script_version`, `adapter_version`, and an action fingerprint where relevant.

Message categories: hello, capabilities, state snapshot, state delta, event,
command request, command accepted/rejected/started/completed/failed, heartbeat,
error, save, load, and resynchronization request. Unknown message types are
rejected; unknown envelope fields are rejected in v1; payload schemas may allow
documented forward-compatible fields. Major protocol mismatch fails closed.

Message and command IDs are UUID-like stable IDs. Responses echo the command ID
as `correlation_id`. The GameScript saves a bounded completed-command ledger and
returns the previous terminal outcome for duplicates in production (the probe
only rejects duplicates). Sequence is monotonic within a script instance; gaps
or a changed instance ID trigger full resynchronization. A snapshot is sent on
connect/load/new game and periodically; deltas name their base snapshot.

Error codes: `unsupported_command`, `invalid_company`, `invalid_tile`,
`insufficient_funds`, `game_rule_rejection`, `stale_request`,
`duplicate_request`, `script_unavailable`, `context_unavailable`,
`protocol_mismatch`, and `internal_script_failure`.

Security: loopback by default; Admin password remains the transport credential;
RCON is not a bridge dependency. Validate strict JSON and payload schemas,
allowlist commands, apply the 8,999/1,450-byte limits, rate-limit per connection,
never include secrets in messages, deny public multiplayer writes by default,
and require an explicit write opt-in plus selected company.

## 12. Capability negotiation, persistence, and recovery

Capabilities report script/protocol/API/OpenTTD identity, read resources, write
actions, company contexts, test-cost/verification/reconciliation support, saved
state generation, last sequence, and health. Compiler, decision provider, policy,
and evaluator consume only the intersection of negotiated and locally allowed
capabilities. Initially that means rich reads plus company state/name probe—not
construction.

Before a future command, Sim Pilot persists intent, command ID, action
fingerprint, expected precondition, and checkpoint. It then waits for accepted,
terminal response, and independent observation before committing completion.
On any restart it sends a resynchronization request and reconciles the durable
intent against GameScript's saved command ledger and current state.

Actions classify as naturally idempotent (set desired setting), state-comparable
(name/loan/order configuration), command-ID deduplicated (create/build),
compensatable (temporary sign/road), ambiguous (multi-step construction), or
unsafe for autonomous retry (sell, clear, terraform). Ambiguous/unsafe actions
must suspend for observation or approval.

## 13. Installation, compatibility, and licensing

The bridge must be installed as a GameScript and selected for a new game. A save
already bound to another GameScript cannot simply run both; exactly one is
active. Loading a bridge save without the package leaves the game running but
automation unavailable. Dedicated server is recommended because Admin Network
must be enabled and authenticated. Existing bridge-enabled saves carry script
state; ordinary saves require an explicit compatibility/migration story.

OpenTTD is GPLv2. Squirrel scripts distributed separately are not a patched
OpenTTD binary, but redistributed OpenTTD modifications would require GPL source
compliance. Script packaging must also respect any borrowed library licenses.
No patch is selected for Task 7B.

## 14. Unsupported and constrained product capabilities

- No complete game-speed API, livery API, universal route/pathfinding API, or
  exact GUI-level status/catchment representation.
- No durable delivery supplied by Admin/GameScript transport; Sim Pilot must add
  IDs, ledgers, resynchronization, and verification.
- No message queue while all Admin clients are disconnected.
- No simultaneous second GameScript and no takeover of a NoAI company's script.
- No proof yet for human-company road/rail/station/vehicle construction, its
  exact cost parity, removal, ownership, or persistence.
- No production claim for route planning, station placement, vehicle workflows,
  or autonomous retry of destructive commands.
- Map-wide snapshots are too expensive and too large for one message; paging and
  tick budgets are mandatory.

## 15. Risks and Task 7B recommendation

Principal risks are save compatibility, script failure leaving the game running
without automation, small outbound packets, tick-budget pressure, entity-ID
changes, duplicate commands across save boundaries, and API drift after 15.3.

The **Task 7B constrained scope** is now implemented as follows:

1. Protocol v1 provides strict typed messages, subscription, hello, capability
   negotiation, full snapshots, heartbeat, resync, and a saved command ledger.
   Deltas remain unsupported.
2. Expose the verified richer read catalog and cross-check shared company fields
   against Admin Network.
3. Keep all writes opt-in and capability-gated.
4. A future milestone may add a disposable human-created company fixture and must require a road
   test/build/observe/remove/save/reload probe before promoting construction to
   supported.
5. Do not add UI control, NoAI indirection, or a patched OpenTTD build.
