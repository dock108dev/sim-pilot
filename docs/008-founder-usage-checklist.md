# Founder Usage Checklist

**Status:** Phase 7.6 affected-workflow rerun passed

**Execution date:** 2026-07-19

**Executor:** Codex, explicitly authorized by the owner to perform the manual pass

## Environment and safety

- Repository: `/Users/michaelfuscoletti/Desktop/sim-pilot`
- Disposable database: `data/founder-usage-20260719.db`
- OpenTTD: 15.3 dedicated server on `127.0.0.1:3979`
- Admin Network: protocol 3 on `127.0.0.1:3977`
- Disposable source save: `task7b-bridge-production-v2.sav`
- Disposable save/load copy: `founder-usage-20260719.sav`
- Company: 0
- Bridge: protocol 1, stable instance `spb-1636440848-1049736244`
- Capability fingerprint: `a4868cb5227ad0e126764cb2312b52573218087ab6f5d145a7c8a60877db55ca`
- Secrets were read from the existing local OpenTTD configuration and were not written to artifacts.
- All writes were loopback-only and limited to the disposable server and save.

Rating scale: 1 unusable, 2 frustrating, 3 workable, 4 good, 5 natural.
Unless stated otherwise, terminology and failure output were clear, no feedback was missing, and
setup difficulty was low after the standard environment was configured.

## Repository and configuration

| Done | Workflow and command | Expected and actual result | Friction / failure quality | Rating | Desired next capability |
|---|---|---|---|---:|---|
| [x] | Fresh setup — `uv python install 3.12`; `uv sync --dev` | Python 3.12.12 installed; 35 packages audited. | Fast and reproducible. | 5 | None. |
| [x] | Database migration — `SIM_PILOT_DATABASE=... uv run sim-pilot db upgrade` | Applied revisions `0001` and `0002`; printed `database upgraded`. | Clear result. | 4 | Print the resulting revision. |
| [x] | Migration state — `SIM_PILOT_DATABASE=... uv run alembic current` | Expected `0002`; command inspected the URL in `alembic.ini` and printed no revision. Direct SQLite verification showed `0002` in the disposable database. | Environment variable and raw Alembic CLI use different database selection rules. | 2 | Add `sim-pilot db current` or make Alembic honor the application URL. |
| [x] | Configuration error — admin doctor without password | Returned structured `configuration_valid: false` and named the missing variable without exposing secrets. | Good message, but configuration-invalid doctor does not signal failure through an obvious terminal status. | 4 | Include remediation and a nonzero status for invalid configuration. |
| [x] | Offline provider default — `task compile -i "Reach one million cash"` | Failed before a hosted call with exit 20 and explicit provider choices. | Strong fail-closed behavior. | 4 | None. |
| [x] | Explicit provider — same command with `--provider codex` | Valid `intent-compiler-v3` report through the authenticated Codex surface. | Roughly 8 seconds is noticeable. | 4 | Progress feedback during hosted calls. |

## Reference simulation and durable runtime

| Done | Workflow and command | Expected and actual result | Friction / failure quality | Rating | Desired next capability |
|---|---|---|---|---:|---|
| [x] | Compile — `task compile --provider codex -i "Reach 520000 cash without taking loans"` | Correct cash objective and loan prohibition. | Output is detailed but trustworthy. | 4 | Concise human summary before JSON. |
| [x] | Create — matching `task create ... --yes` | Persisted task `259b4ef2-c66c-4ada-a160-470e25b78fba`. | The command prints the full compiler report and task, which is verbose. | 4 | End with a prominent task ID. |
| [x] | Scripted run — `task run TASK_ID --decision-provider scripted --iterations 1` | Advanced one tick, checkpointed, remained running. | Clear outcome and provider metadata. | 4 | A shorter default view. |
| [x] | Hosted run — same task with `--decision-provider codex` | **Failed:** `Codex CLI exited with status 1: Reading additional input from stdin...`. | Failure closed safely, but the command then printed stale metadata from the previous scripted decision. | 1 | Repair Codex decision invocation and never print prior decision metadata as if it belongs to a failed call. |
| [x] | Approval — scripted task requiring approval, then `task approve bff94105-...` | Waited before execution; approval persisted; resume executed exactly once. | Approval uses approval ID rather than task ID, but output makes it discoverable. | 4 | `task approve --task TASK_ID` convenience. |
| [x] | Denial — second request, then `task deny 9eecb85b-...` | Denial persisted and task became blocked with `approval denied`. | Clear and predictable. | 4 | None. |
| [x] | Cancellation — `task cancel b26779aa-...`; `task show` | Pending task became terminal `cancelled`. | Clear. | 4 | Return the updated task from cancel. |
| [x] | Process restart — separate `task show` process | Reconstructed task, checkpoint, tick, observation sequence, and restrictions. | Durable behavior is convincing. | 4 | Add a concise resume-readiness field. |
| [x] | Resume — separate `task resume ... --iterations 1` process | Loaded tick 1, executed once, persisted tick 2. | No replay or duplicate action observed. | 4 | None. |
| [x] | Events — `task events a4c78508-...` | Printed 24 strictly ordered append-only events covering approval, action, verification, checkpoint, and denial. | Accurate but difficult to scan. | 3 | Filters, summary mode, and event-type coloring. |
| [x] | Recovery inspection — prepared crash after execution; `task recovery show ...9001` | Classified `adapter_unavailable` and showed prior snapshot without guessing. | Honest but setup requires Python/internal hooks. | 3 | Public disposable crash-fixture command. |
| [x] | Recovery resolution — `task recovery resolve ... restore_prior_checkpoint` | Cleared the unresolved attempt without retrying the action. | Resolution names are technically precise but operator-heavy. | 3 | Recommend safe choices in CLI output. |
| [x] | Failed task — `task show 259b4ef2-...` after hosted decision failure | Durable failed state retained the provider error. | Stale prior decision metadata in the original failure output is misleading. | 2 | Correlate displayed metadata to the current attempt only. |
| [x] | Blocked task — denied approval task | Durable blocked state and reason were clear. | Good failure quality. | 4 | None. |

## OpenTTD Admin integration

| Done | Workflow and command | Expected and actual result | Friction / failure quality | Rating | Desired next capability |
|---|---|---|---|---:|---|
| [x] | Doctor — `openttd doctor` | Connected to 15.3/protocol 3 on company 0. | Static capability block reports safe defaults rather than live bridge/write state. | 4 | Clearly label configured versus negotiated capabilities. |
| [x] | Capabilities — `openttd capabilities` | Correctly showed read-only defaults with writes disabled. | Safe, but users may mistake defaults for live capability discovery. | 3 | Add `--live` or rename to `default-capabilities`. |
| [x] | Observe — `openttd observe` | Captured canonical timestamp, tick, cash, debt, value, counts, date, and server name. | Very large JSON for a routine observation. | 3 | Concise table plus `--json`. |
| [x] | Watch — `openttd watch --count 5` | Printed only date, cash, and profit changes over five observations. | Useful and readable. | 4 | Optional field selection. |
| [x] | Disabled write — server-name action without write flag | Rejected with exit 23 and made no change. | Excellent fail-closed result. | 5 | None. |
| [x] | Server-name write — action with explicit flag | Changed `simpilot` to `Sim Pilot Founder Test`, reconnected, and independently verified it. | Full before/after output is excessive. | 4 | Concise verification summary and optional full evidence. |
| [x] | Stale-state rejection — focused adapter acceptance scenario | Rejected stale economy state without issuing RCON. | Passed, but there is no public CLI fixture to reproduce this workflow. | 2 | Disposable fault-injection command. |

## GameScript bridge

| Done | Workflow and command | Expected and actual result | Friction / failure quality | Rating | Desired next capability |
|---|---|---|---|---:|---|
| [x] | Doctor — `openttd bridge doctor` | Synchronized protocol 1, company 0, full snapshot, stable identity. | Strong diagnostics. | 4 | Concise healthy summary by default. |
| [x] | Capability negotiation — `bridge capabilities` | Returned the expected fingerprint and bounded `set_company_name` action. | Clear. | 4 | None. |
| [x] | Snapshot — `bridge observe` | Admin and bridge identities agreed; towns, industries, pause, and company data were merged. | Large JSON and transient cash inconsistency is noisy but explicitly attributed. | 3 | Concise view and tolerance-aware inconsistency display. |
| [x] | Reconnect — two independent bridge clients and live acceptance test | Script instance remained stable and sequence increased. | Automatic and reliable. | 4 | Surface reconnect count. |
| [x] | Save/load — low-level bounded RCON save/load; `bridge sync` | Created `founder-usage-20260719.sav`; reload preserved instance identity and advanced save generation from 297 to 298. | No public save/load exercise command; required internal client use. | 3 | Disposable `bridge exercise save-load` command. |
| [x] | Company-name write — explicit bridge write flag | Changed and independently verified `Sim Pilot Founder Test`. | Clear proof, overly verbose output. | 4 | Concise proof mode. |
| [x] | Duplicate command — bounded bridge client with stable command ID | First result `duplicate: false`; second `duplicate: true`; fingerprints matched; one mutation. | Correct durable ledger behavior. | 4 | Public diagnostic command. |
| [x] | Conflicting duplicate — same command ID, different name | Rejected with `duplicate_conflict`; state was restored to the founder-test name. | Precise failure. | 4 | Public diagnostic command. |
| [x] | Identity mismatch — synthetic prior identity against live bridge | Failed closed with `BridgeSequenceError: script identity changed`. | Strong trust boundary. | 4 | Operator remediation guidance. |
| [x] | Crash recovery — injected crash after verified `set_company_name` | **Failed:** the write executed, but recovery dispatched to reference replay and raised `unsupported reference adapter snapshot`. The company name was independently observed and restored. | Advertised reconciliation is not implemented for this action. | 1 | Implement `set_company_name` reconciliation from fresh bridge identity and company name, with no retry. |

## Result

All 37 workflows were exercised. Thirty-five behaved as intended or exposed only usability
friction. Two failed product workflows require correction:

1. Codex CLI runtime decisions currently fail at subprocess input handling and display stale prior
   decision metadata afterward.
2. GameScript `set_company_name` crash recovery is advertised but has no action-specific
   reconciliation dispatcher.

The disposable server and company names were restored to `Sim Pilot Founder Test`. The founder
database and disposable save remain local for follow-up diagnosis.

## Phase 7.6 affected-workflow rerun

**Rerun date:** 2026-07-19

Only workflows touched by the stability fixes were repeated.

| Done | Workflow | Corrected result | Rating |
|---|---|---|---:|
| [x] | Codex compile and create | Both used `gpt-5.6-sol` through Codex CLI 0.144.6 and produced valid `intent-compiler-v3` specifications. | 4 |
| [x] | Codex run and resume | Runtime decisions executed successfully; three identical-context calls had unique invocation and request IDs. | 4 |
| [x] | Repeated calls | One/two/ten-call offline suites passed for compiler and decision providers; three consecutive live decisions passed. | 4 |
| [x] | Deterministic provider failure | An intentionally unsupported model exposed the actual JSONL 400 error; no prior decision metadata was printed. | 5 |
| [x] | Fresh invocation after failure | A new task immediately succeeded through `gpt-5.6-sol`; no parser, output, recording, or metadata state leaked. | 5 |
| [x] | Cancellation | A pending task remained cancellable after provider changes. | 4 |
| [x] | OpenTTD reconnect and rename | Bridge synchronization and verified company rename passed on the disposable loopback server. | 4 |
| [x] | OpenTTD crash recovery | Injected crash after `set_company_name`, process-level reconstruction, fresh reconnect, definite-executed reconciliation, manual mark-executed, resume, and completion all passed without retry. | 5 |
| [x] | Restoration | The live test restored the original company name after verification. | 5 |

The original failed rows remain above as historical founder-pass evidence. Their corrected status
is authoritative in this rerun section and in `docs/012-phase-7.6-stability-report.md`.
