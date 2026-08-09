# Successor Game Decision Packet

**Status:** Proposed, not accepted

**Date:** 2026-08-09

**Recommendation:** **PROBE GAME — Minami Lane**

## Decision boundary

This packet recommends exactly one next game to probe and one preferred opening interaction. It
does not select a successor, authorize an adapter, change the default adapter, reopen Software
Inc., extend Rail Route, or grant gameplay automation authority.

The recommendation is a probe rather than a selection because none of the required candidates is
installed. No candidate process, exact installed version, app architecture, accessibility tree,
window capture, save format, log content, or post-action state was hands-on proven during this
milestone. Installing even a free official demo requires owner approval; purchasing a game also
requires exact approval.

## Product gate

A successor must prove this complete loop before adapter implementation is proposed:

1. The player types one short terminal objective.
2. A fresh observation identifies one unique visible target.
3. Sim Pilot derives the target from the current frame, not stored coordinates.
4. Sim Pilot sends one ordinary player-visible gesture.
5. A separate fresh observation verifies a semantic and visible postcondition.
6. The player immediately understands the change and its value.
7. Spending and irreversible consequences remain default-no approvals.

An app bundle, save, log, assembly, socket, API, Workshop, editor, or available Accessibility
permission is discovery evidence only. It is not observation, action, or verification proof.

## Contract review

The governing documents are consistent for this decision:

- `000-vision.md` requires game selection before implementation and a short terminal-first loop.
- `001-month-1-design.md` requires one action per cycle, deterministic validation, re-observation,
  verification, bounded authority, and no automatic retry across an ambiguous side effect.
- `002-reference-simulation.md` keeps the deterministic reference engine separate from production
  adapters.
- `024-game-bridge-protocol.md` keeps semantic bridges read-only and gameplay mutation in a
  separately reviewed capability boundary.
- `037-software-inc-freeze-checkpoint.md` freezes Software Inc., forbids transferring its evidence,
  and supplies the next-game gate used here.
- `known-limitations.md` says no successor is selected and both existing game-specific action
  catalogs remain bounded to their own evidence.

No governing-document conflict was found.

## Mac environment summary

Read-only local audit on 2026-08-09:

| Field | Observed value |
|---|---|
| Model | MacBook Pro (`Mac15,6`) |
| Chip and architecture | Apple M3 Pro, 11 cores; `arm64` |
| Memory | 18 GB |
| macOS | 26.5.2, build 25F84 |
| Graphics family | Integrated Apple M3 Pro; Metal 4 |
| Rosetta | Installed |

The audit intentionally omitted the serial number, hardware UUID, Apple ID, Steam identity, and
credentials.

### Installed-game audit

The Steam library contains Rail Route and Software Inc. only. Their app bundles and Steam
manifests were inspected read-only solely to establish that they are the installed frozen/reference
games. Neither was launched, modified, or treated as a successor. No required candidate app,
manifest, running process, residual save folder, or log folder was found under the inspected Steam,
Application Support, Logs, or Preferences locations.

Consequently, this packet makes no hands-on claim for a successor candidate. Software Inc. and Rail
Route geometry, fields, versions, architecture evidence, saves, logs, bridges, and mutation proofs
are not transferred.

## Pass/fail screening and weighted comparison

The first four candidates clear documentary pre-screening: each has an official current Mac
listing and a plausible one-gesture fixture without unsupported injection. Their disposition is
still **conditional** because the action and postcondition have not been live-proven on this Mac.
Train Valley 2 fails the opening product gate described below and is not scored.

Scores are integers from 1 to 5 before weighting. They rank probe priority only; they do not promote
conditional evidence to proof.

| Candidate | Appeal 30% | First loop 20% | Verification 20% | Semantic potential 15% | Mac/setup 10% | Cost/risk 5% | Weighted | Disposition |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Minami Lane | 5 | 5 | 4 | 2 | 5 | 5 | **4.35** | **Conditional — probe** |
| Factorio demo | 3 | 3 | 5 | 5 | 5 | 5 | 4.00 | Conditional — do not probe first |
| Game Dev Tycoon | 4 | 3 | 4 | 4 | 2 | 3 | 3.55 | Conditional — do not probe first |
| Mini Metro | 4 | 5 | 3 | 2 | 3 | 3 | 3.55 | Conditional — do not probe first |
| Train Valley 2 | — | — | — | — | — | — | — | Reject for this first proof |

Factorio's technical surface does not override its lower player-fit score or the risk of recreating
the broad-dependency problem. Minami Lane wins because it is a short, friendly management game
whose first proof is also ordinary play: one street-cleaning action with an immediate visible
result. The player-fit judgment is an inference from prior owner feedback favoring smaller,
approachable management loops over another complex simulation.

## Candidate evidence packets

### Minami Lane

| Field | Evidence and assessment |
|---|---|
| Mac compatibility and architecture | **Officially supported:** Steam lists macOS 10.14+, Apple Silicon, and x64 with SSE2. Native `arm64` execution on this M3 is expected but not locally proven. |
| Cost and demo | **Time-sensitive:** $4.99 list, $3.34 observed sale price on 2026-08-09; no current Steam demo. A pre-release demo ended in 2024. |
| Player appeal | **Inference:** unusually strong fit for the requested smaller management loop: 2–4 hours, shops, prices, happiness, missions, and light strategy rather than a sprawling tech tree. |
| Time to fixture | **Estimate:** 5–15 minutes after install, or immediate after loading a reproducible disposable fixture with exactly one visible trash object. |
| Exact starting state | Disposable English-language mission/sandbox, game not occluded, exactly one trash object visible, trash-collected count readable, no modal, and no day transition in progress. Exact mission and save identity remain to be discovered. |
| Plain-English instruction | `Pick up that piece of trash.` |
| Fresh observation source | Exact-window screenshot with current process/window identity; object detection for trash and OCR for the displayed collected count. No save parser is assumed. |
| Visible target | The one current-frame trash object, uniquely bounded by visual features and window-relative geometry. |
| One gesture | One ordinary click at the center of the freshly detected target. |
| Semantic and visible postcondition | The same target region no longer contains trash and the displayed trash-collected count increases by exactly one. |
| Independent verification | A new exact-window capture after UI settling, independently acquired by the observer rather than inferred from the click result. Both target absence and counter delta must agree. |
| Save/reload | **Unknown:** publisher notes prove saves and the displayed trash count exist, but this exact action's persistence and the Mac save format were not inspected. The probe must test reload without relying on it for the immediate proof. |
| Spending/irreversibility | The click has no known in-game spending. Use a disposable fixture because trash removal changes game state. Purchase/download requires owner approval. |
| Official extension surface | No official mod API, level editor, or Workshop feature is listed. Steam Cloud is listed. The first proof intentionally needs none. |
| Accessibility and screenshot feasibility | **Inferred:** trackpad/controller UI and a visible object make screenshot control plausible. Accessibility tree depth, exact-window capture, and permissions are hands-on unknowns. |
| Save/log discovery | Publisher notes confirm save fixes and a `Player.log` support workflow, but the Mac paths, schemas, freshness, and semantic value are unproven. |
| Known uncertainty | Exact mission, target sprite variability, count location, animation settling, pause behavior, foreground/window stability, capture permission, and reload persistence. |
| Estimated adapter effort | **Estimate:** 4–7 engineer days after a successful probe for a one-capability screen-only adapter, fixture contract, tests, CLI composition, and acceptance evidence. |
| Disposition | **Conditional — recommended bounded probe.** |

### Factorio demo

| Field | Evidence and assessment |
|---|---|
| Mac compatibility and architecture | **Officially supported and native:** Wube documents a universal binary and native Apple-silicon support since 1.1.71. Current stable demo is 2.0.77; this Mac exceeds the 8 GB minimum. Not locally installed. |
| Cost and demo | Free official macOS demo; full game is $35.00. Download requires owner approval. |
| Player appeal | **Inference:** exceptional engineering depth, but factory construction risks the same early breadth that froze Software Inc. The demo is explicitly a basic-mechanics tutorial subset. |
| Time to fixture | **Estimate:** 10–20 minutes to a tutorial fixture with one burner drill in inventory and one uniquely visible ore target. |
| Exact starting state | Disposable demo tutorial, one burner mining drill selected, one unobstructed valid ore tile, no enemies or modal, game paused if the tutorial permits it. |
| Plain-English instruction | `Place the burner drill on that iron patch.` |
| Fresh observation source | For the demo probe, exact-window screenshot only. The full game's Lua runtime, script output, logs, saves, scenarios, and command options are strong supported surfaces but must not be assumed available to the demo. |
| Visible target | Unique valid ore tile under a placement preview. |
| One gesture | One click to place the already-selected drill. |
| Semantic and visible postcondition | Drill appears at the target and the selected inventory stack decreases by one. |
| Independent verification | New screenshot verifying both world entity and inventory delta; a full-game read-only Lua observer would be stronger but is outside the demo's proven boundary. |
| Save/reload | Official full-game user-data docs list saves, mods, scenarios, script output, and logs. Demo persistence and custom scenario support are unproven. |
| Spending/irreversibility | No real spending for the demo. Placement changes a disposable tutorial. Full-game purchase and any portal account use require approval. |
| Official extension surface | Full game has Lua mod APIs, scenarios, map editor, script output, UDP options, and a mod portal. Wube's terms reserve the mod portal/in-game integration to purchasers. The demo's custom mod/scenario lifecycle is not officially established by the reviewed sources. |
| Accessibility and screenshot feasibility | **Inferred:** visually clear grid and selected-item state; accessibility tree and capture behavior unproven. |
| Known uncertainty | Whether the demo permits a reproducible custom fixture, local mod execution, script output, pause-at-fixture, and a sufficiently simple route into the proposed state. |
| Estimated adapter effort | **Estimate:** 5–8 engineer days after a successful full-game semantic probe; screenshot-only demo control would be cheaper but too weak to justify the game's complexity. |
| Disposition | **Conditional — strong technical reference, not the first product probe.** |

### Game Dev Tycoon

| Field | Evidence and assessment |
|---|---|
| Mac compatibility and architecture | **Official Mac listing:** Steam states macOS 10.7.5+, but the published requirements and Greenheart changelog are old and do not establish current Apple-silicon architecture. Intel/Rosetta is the conservative expectation; exact execution on macOS 26 is unproven. |
| Cost and demo | $9.99. Greenheart still offers a free Mac demo, but explicitly says it is old version 1.3.9 and limited to year five/garage; it is not a current compatibility proof. |
| Player appeal | **Inference:** approachable management theme and likely stronger sustained interest than a pure puzzle, but even the first game requires topic, genre, platform, features, sliders, and a final commitment. |
| Time to fixture | **Estimate:** 5–15 minutes to a garage fixture with the first game's definition completely prepared and only the final commitment visible. |
| Exact starting state | Disposable garage save, English UI, `Develop New Game` final confirmation open, exact name/topic/genre/platform/options already visible and validated, no modal. |
| Plain-English instruction | `Start developing this Adventure game.` |
| Fresh observation source | Preferred future source is a new read-only local mod snapshot plus exact-window screenshot. The official Mod API exists, but its ability to expose the exact prepared/active-game state has not been proven. |
| Visible target | The unique final create/start button in the current dialog. |
| One gesture | One click on the freshly detected final commitment button. |
| Semantic and visible postcondition | A uniquely named active game project exists and its development activity is visibly underway; any exact cash commitment matches the approved amount. |
| Independent verification | Fresh read-only mod snapshot plus new screenshot. Save-only observation is not accepted because the historical `file__0.localstorage` location does not prove safe, fresh semantic decoding. |
| Save/reload | Greenheart historically documents the Mac local-storage save and Steam Cloud. Exact current schema, atomicity, and project persistence are unproven. |
| Spending/irreversibility | Final project commitment is an in-game economic decision. Require exact default-no approval if observed cost is nonzero. Use a disposable save. |
| Official extension surface | Official Mod API ships with version 1.5.0+, plus Workshop support and a modding agreement. The reviewed official changelog labels Steam 1.5.28 as latest but is dated 2015, so live version detection is mandatory. |
| Accessibility and screenshot feasibility | **Inferred:** point-and-click HTML/JavaScript UI should be visually tractable. Current accessibility tree, window capture, and node-webkit behavior on this Mac are unknown. |
| Known uncertainty | Modern macOS launch, executable architecture, current Steam version, mod lifecycle, read-only state coverage, exact commitment cost, and whether the final click is sufficiently satisfying in isolation. |
| Estimated adapter effort | **Estimate:** 7–10 engineer days after compatibility/mod probing for a read-only observer, screen action, fixture, and exact economic approval. |
| Disposition | **Conditional — promising later candidate, not the first probe.** |

### Mini Metro

| Field | Evidence and assessment |
|---|---|
| Mac compatibility and architecture | **Official Mac listing:** current Steam page supports modern macOS. Publisher updates moved the game to Unity 2022.3 and patched a Mac Metal focus issue. Native Apple-silicon architecture is not stated; Intel/Rosetta is the conservative expectation and is unproven locally. |
| Cost and demo | $9.99 list; no current official demo shown. Purchase/download requires approval. |
| Player appeal | **Inference:** very clean, relaxing transit puzzle with an obvious visual payoff and little opening complexity. It is less of a management/vacation-style loop than Minami Lane. |
| Time to fixture | **Estimate:** 2–5 minutes in Creative mode to a city with exactly three stations and no lines. |
| Exact starting state | Disposable Creative map, exactly one circle and one triangle chosen as endpoints, no existing line between them, one line color selected, no modal. |
| Plain-English instruction | `Connect the circle station to the triangle station.` |
| Fresh observation source | Exact-window screenshot detecting station shapes, line colors, and current network topology. No semantic API is assumed. |
| Visible target | Unique circle and triangle endpoint pair in the current frame. |
| One gesture | One drag from the circle center to the triangle center. |
| Semantic and visible postcondition | One continuous selected-color line connects the two shapes and train service begins if the mode starts service automatically. |
| Independent verification | New screenshot with topology recognition. There is no reviewed supported semantic state source to distinguish a functional line from a merely drawn visual if service does not start. |
| Save/reload | Steam Cloud and map export are listed features; exact autosave/reload behavior for the disposable Creative fixture is unproven. |
| Spending/irreversibility | No real spending and no expected in-game currency. Use a disposable map because topology changes. |
| Official extension surface | Steam Workshop, an official Workshop map guide, Creative mode, and player-created maps. No public gameplay API was found. Third-party Workshop content is not needed or authorized. |
| Accessibility and screenshot feasibility | **Inferred:** mouse-only, high-contrast shapes make vision attractive. Accessibility tree and exact-window behavior are unproven. |
| Known uncertainty | Architecture, shape overlap, animated station growth, line-tool behavior, functional-service verification, and persistence. |
| Estimated adapter effort | **Estimate:** 4–7 engineer days for robust topology vision, drag validation, fixture, and tests; semantic confidence remains weaker than the visual simplicity suggests. |
| Disposition | **Conditional — best visual runner-up, not the first probe.** |

### Train Valley 2

| Field | Evidence and assessment |
|---|---|
| Mac compatibility and architecture | **Official Mac listing:** macOS 10.12+ with Intel Core i5 requirements. Intel/Rosetta is the conservative expectation; local launch and exact architecture are unproven. |
| Cost and demo | $14.99; no current official demo shown. |
| Player appeal | **Inference:** bounded train puzzles and company progression fit the desire for a simpler train game. |
| Time to fixture | **Estimate:** 15–30 minutes to create and validate an editor-authored disposable level. |
| Exact starting state | Editor fixture with one factory, one town, clear terrain, rail tool selected, and no existing route. |
| Plain-English instruction | `Connect the factory to the town.` |
| Fresh observation source | Screenshot-derived endpoints, route clearance, tool state, and current track geometry. |
| Visible target | Factory endpoint and town endpoint. |
| One gesture | One drag intended to lay a continuous track path. |
| Semantic and visible postcondition | Track appears between endpoints. Functional connectivity, train movement, and delivery do not necessarily follow from that gesture alone. |
| Independent verification | Screenshot can verify rendered track, but no reviewed semantic API can independently establish route validity; starting a train would require another action. |
| Save/reload | Steam Cloud, Workshop, and a level editor are official. Save schema and reload persistence are unproven. |
| Spending/irreversibility | Track normally carries in-game cost; use an editor fixture or require exact approval in a company level. |
| Official extension surface | Steam Workshop and level editor; no public gameplay API found. |
| Accessibility and screenshot feasibility | **Inferred:** visible 3D endpoints and drag action, but perspective, terrain, routing, and camera state make detection materially harder than Mini Metro. |
| Known uncertainty | Exact route tool semantics, pathfinding, cost, camera projection, route validity, save format, and architecture. |
| Estimated adapter effort | **Estimate:** 8–12 engineer days due to 3D geometry, drag-path validation, economy policy, and weak independent verification. |
| Disposition | **Reject for this first proof:** one track drag does not independently prove a functional connection, and a second action would violate the proposed opening loop. |

## Rejected and non-selected candidates

- **Train Valley 2 — rejected:** the proposed drag proves rendered track at best, not a functional
  route. A train start/delivery would add another action, and company-mode construction may spend
  in-game money.
- **Factorio demo — not selected:** technically strongest, but the demo is a tutorial subset and
  the reviewed official evidence does not establish its custom mod/scenario lifecycle. Its broad
  factory graph is also a poor first response to the Software Inc. freeze.
- **Game Dev Tycoon — not selected:** official modding is promising, but current Apple-silicon
  execution, current version, read-only state coverage, and a truly bounded meaningful first
  commitment all need proof.
- **Mini Metro — not selected:** the drag is excellent, but verification is presently screenshot
  topology only, functional service and reload are unproven, and native-vs-Rosetta execution is not
  documented.

## Recommended candidate

**PROBE GAME — Minami Lane**

This is not `SELECT GAME`: purchase, installation, launch, screenshot/accessibility behavior, exact
fixture, one-click mutation, counter verification, and reload behavior remain unproven. It is not
`SELECT NONE` because the official evidence supports one unusually small, player-visible, and
enjoyable-looking experiment with no in-game spending.

### Preferred first loop

Game: Minami Lane<br>
Starting fixture: Disposable English mission/sandbox with exactly one visible trash object and a
readable trash-collected count; no modal or transition.<br>
Terminal instruction: `Pick up that piece of trash.`<br>
Fresh observation: New exact-window screenshot binds process/window/frame identity, reads the
current count, and detects exactly one trash object.<br>
Visible target: The unique current-frame trash bounding box.<br>
One gesture: One click at the freshly derived target center.<br>
Fresh post-action observation: A separately captured exact-window screenshot after animation/UI
settling.<br>
Independently verified postcondition: The target is absent and the displayed count is exactly one
higher; both must agree.<br>
Player-visible value: The street is visibly cleaner and the game's own collection progress
advances.<br>
Approval required: Owner-approved purchase/download and disposable fixture; macOS Screen Recording
or Accessibility permission if absent. No per-click economic approval.<br>
Failure behavior: If the target is absent, duplicated, occluded, stale, or the counter is unreadable,
block before input. If input may have been sent but either postcondition is ambiguous, stop without
retry and require reconciliation.

### Fallback first loop

Game: Minami Lane<br>
Starting fixture: Disposable English save with one uniquely named ramen shop's management panel
open, exact current ramen price readable, and the one-step increment control visible.<br>
Terminal instruction: `Raise this ramen price by one step.`<br>
Fresh observation: New exact-window screenshot reads the shop identity, current exact price, and
unique increment control.<br>
Visible target: The current-frame one-step increment control for ramen price.<br>
One gesture: One click on that control.<br>
Fresh post-action observation: Separately captured panel screenshot after UI settling.<br>
Independently verified postcondition: Same shop and product, new price equals the observed old price
plus exactly one UI step, and no other displayed setting changed.<br>
Player-visible value: The player sees a concrete shop-management decision that affects the next
day's economics.<br>
Approval required: No real or in-game spending expected; the disposable save is required because
the setting changes.<br>
Failure behavior: Block before input on ambiguous shop/product/control or unreadable price. Never
retry a possibly sent price change; re-observe and reconcile the exact displayed value.

## Smallest future adapter boundary

If the owner later selects Minami Lane after a successful probe, the first implementation should be
a separate one-capability screen adapter:

- read-only exact-window observation of process/window identity, one trash target, and collection
  count;
- current-frame target derivation with no persisted screen coordinate;
- a catalog containing only `collect_visible_trash` for the accepted fixture/version;
- deterministic pre-input validation, one click, new capture, dual postcondition verification, and
  no automatic retry;
- owner-only evidence that stores identities, bounding boxes, counts, and outcomes without retaining
  screenshot pixels by default.

It should not start with a mod, save parser, semantic bridge, dashboard, continuous controller,
shop optimizer, day runner, or generalized object detector. Save/log discovery remains read-only
until freshness, atomicity, schema, and value are separately proven.

## Probe approvals and limits

The recommended owner response is `probe`. In this packet, that means approval for exactly:

- one Steam purchase of Minami Lane at no more than **$4.99 USD before tax**;
- official Steam download/install on this Mac;
- read-only executable/version/save/log/window/accessibility/screenshot discovery;
- one reproducible disposable fixture;
- one manual preferred-loop trash click and fresh post-action observation;
- save/reload inspection of that disposable fixture.

It does not approve third-party tools or mods, broad accessibility tooling, injection, an adapter,
source implementation, background automation, another paid game, or additional gameplay mutation.

## Evidence still missing

- Actual installed version and executable architecture on this Mac.
- Native-vs-Rosetta process observation.
- Exact save/log locations, formats, freshness, and reload behavior.
- Accessibility tree availability and whether it adds useful semantics.
- Exact-window screenshot behavior, resolution, scaling, focus, and permission state.
- A reproducible fixture with exactly one visible trash object and a readable counter.
- Current-frame target precision and animation settling.
- One-click target removal, exact counter delta, and persistence after reload.
- Confirmation that this loop is enjoyable enough for the owner to choose the game.

## Rough implementation effort

After a successful probe and separate adapter authorization: **4–7 engineer days** for the exact
one-capability vertical slice, including fixture, typed contracts, policy and failure paths, CLI
composition, tests, documentation, and live acceptance. This is not a roadmap or implementation
commitment.

## Exact acceptance criteria for a later implementation

1. The owner has explicitly selected Minami Lane and separately authorized adapter work.
2. A pinned installed version and observed process architecture run reliably on this Mac.
3. A disposable, reproducible fixture exposes exactly one visible trash target and readable count.
4. The terminal accepts exactly `Pick up that piece of trash.` inside a one-action catalog.
5. A fresh exact-window observation binds process, window, frame, target, and pre-count.
6. Deterministic validation rejects stale, zero, multiple, occluded, or ambiguous targets.
7. One and only one ordinary click is sent to a target derived from that fresh frame.
8. A separate fresh capture proves target absence and pre-count plus one.
9. A possibly sent but ambiguous action is never retried automatically.
10. The disposable save can be reloaded and its persistence behavior is explicitly reported.
11. No unexpected state, spending, or unrelated UI setting changes.
12. Ruff, Pyright, pytest, fixture tests, failure-path tests, and the exact live acceptance pass.

## Source ledger

All URLs were accessed on 2026-08-09. Prices and store/platform listings are time-sensitive.

| Source | Exact claim supported |
|---|---|
| [Game Dev Tycoon on Steam](https://store.steampowered.com/app/239820/Game_Dev_Tycoon/) | $9.99; Mac listing and requirements; Steam Cloud, Workshop, modding support, game-development flow. |
| [Greenheart Game Dev Tycoon downloads](https://www.greenheartgames.com/game-dev-tycoon-downloads/) | Official Mac demo exists but is old version 1.3.9, limited to year five and the garage. |
| [Greenheart Game Dev Tycoon changelog](https://www.greenheartgames.com/game-dev-tycoon-changelog/) | Official page labels Steam 1.5.28 latest and records Workshop/Mod API events; its last listed release is dated 2015, so it is not treated as live installed-version proof. |
| [Official GDT Mod API repository](https://github.com/greenheartgames/gdt-modAPI) | Official API ships with Game Dev Tycoon 1.5.0+ and includes documentation/examples. |
| [Greenheart modding agreement](https://www.greenheartgames.com/legal/game-dev-tycoon-modding-agreement/) | Noncommercial Mod API use terms; mods are limited to the paid/full game under the agreement. |
| [Greenheart save-location thread](https://forum.greenheartgames.com/t/where-are-the-saved-files-location/1061) | Historical staff-authored Mac local-storage path and `file__0.localstorage` save claim. |
| [Factorio on Steam](https://store.steampowered.com/app/427520/Factorio/) | Current Mac requirements, editor/scenario/mod support, $35.00 US price via the official Steam store API. |
| [Factorio download](https://www.factorio.com/download) | Free macOS demo, current stable demo 2.0.77, and explicit tutorial-subset purpose. |
| [Factorio Apple Silicon announcement](https://www.factorio.com/blog/post/fff-371) | Universal macOS binary and native Apple-silicon support since 1.1.71. |
| [Factorio terms](https://www.factorio.com/terms-of-service) | Demo is free; mod portal and in-game integration are purchaser benefits. |
| [Factorio Lua API](https://lua-api.factorio.com/latest/) | Supported full-game settings/prototype/runtime mod lifecycle and gameplay observation/control potential. |
| [Factorio application directory](https://wiki.factorio.com/Application_directory) | Official user-data locations for saves, mods, scenarios, script output, config, and logs on macOS. |
| [Factorio command line](https://wiki.factorio.com/Command_line_parameters) | Supported scenario loading, mod directory, log, script/data dump, UDP, window, and benchmark options. |
| [Mini Metro on Steam](https://store.steampowered.com/app/287980/Mini_Metro/) | Current Mac listing, $9.99 list price, three-station opening, Creative mode, Workshop, Cloud, mouse-oriented gameplay. |
| [Mini Metro official news](https://steamcommunity.com/app/287980/allnews/) | Current Unity 2022.3 line and publisher's macOS Metal/focus fix; does not establish binary architecture. |
| [Minami Lane on Steam](https://store.steampowered.com/app/2678990/Minami_Lane/) | Mac Apple Silicon/x64 requirements; $4.99 list and observed $3.34 sale; 2–4 hour management loop; shops, prices, happiness, missions, trash, Cloud. |
| [Minami Lane official news](https://steamcommunity.com/app/2678990/allnews/) | Publisher's current 1.1.4p update, save fixes, and existence of a displayed trash-collected count. |
| [Minami Lane Mac announcement](https://steamcommunity.com/ogg/2678990/announcements/detail/4134938965490635895) | Publisher announcement that the game became available for macOS. |
| [Train Valley 2 on Steam](https://store.steampowered.com/app/602320/Train_Valley_2/) | $14.99; Mac Intel requirements; Workshop, Cloud, editor, train-puzzle/company-mode scope. |

The five current US store prices and Mac flags were also cross-checked through Valve's official
`/api/appdetails` endpoint on the access date. Community discussions were used only as discovery
leads unless authored by the developer/publisher and identified above.

## Owner decision required

Reply with one word:

- `probe` — recommended; authorize only the bounded paid probe and limits above.
- `select` — accept Minami Lane as successor without the recommended hands-on proof; still does not
  authorize adapter implementation.
- `reject` — reject Minami Lane and make no purchase or successor change.

**No adapter implementation is authorized yet.**
