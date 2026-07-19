# Founder Usage Checklist

**Status:** Ready for owner execution  
**Rule:** Every checkbox starts incomplete. The owner must run the commands and record the result;
an agent may prepare disposable state but must not mark manual usability complete.

## Test workspace

Use disposable data and a disposable loopback OpenTTD save. Do not use an ordinary save or public
server.

```bash
export SIM_PILOT_DATABASE="$PWD/data/founder-usage.db"
export SIM_PILOT_OPENTTD_HOST=127.0.0.1
export SIM_PILOT_OPENTTD_PORT=3977
export SIM_PILOT_OPENTTD_ADMIN_PASSWORD="<local-admin-password>"
export SIM_PILOT_OPENTTD_COMPANY_ID="<test-company-id>"
```

Keep write flags unset until the relevant write exercise. Codex CLI commands use the existing
authenticated local session. OpenAI API exercises are optional and require an owner-supplied
`OPENAI_API_KEY`.

## Result record

Copy this block once for every checklist row:

```text
Workflow:
Command used:
Expected result:
Actual result:
Setup difficulty:
Confusing terminology:
Unclear output:
Missing feedback:
Failure quality:
Usefulness (1-5):
Desired next capability:
```

Rating scale: 1 unusable, 2 frustrating, 3 workable, 4 good, 5 natural.

## Repository and configuration

- [ ] Fresh setup — `uv python install 3.12 && uv sync --dev`; expect a reproducible environment.
- [ ] Database migration — `uv run sim-pilot db upgrade`; expect `database upgraded`.
- [ ] Migration state — `uv run alembic current`; expect the head revision.
- [ ] Configuration failure — run `uv run sim-pilot openttd doctor` with the admin-password variable
  unset; expect a clear, non-secret-bearing error.
- [ ] Offline compiler default — `uv run sim-pilot task compile -i "Reach one million cash"`; expect
  a clear no-provider-configured failure and no hosted call.
- [ ] Explicit compiler selection — repeat with `--provider codex`; expect a structured compiler
  report identifying the Codex surface.

## Reference simulation

- [ ] Compile — `uv run sim-pilot task compile --provider codex -i "Reach 520000 cash without taking loans"`.
- [ ] Create — repeat as `task create ... --yes`; save the emitted `TASK_ID`.
- [ ] Scripted run — create a simple target task and run `uv run sim-pilot task run TASK_ID --decision-provider scripted --iterations 1`.
- [ ] Hosted run — `uv run sim-pilot task run TASK_ID --decision-provider codex --iterations 1`.
- [ ] Approval — create a task with an approval threshold, run it, then use
  `uv run sim-pilot task approve APPROVAL_ID`.
- [ ] Denial — create another approval request, then use `uv run sim-pilot task deny APPROVAL_ID`.
- [ ] Cancellation — `uv run sim-pilot task cancel TASK_ID` followed by `task show`.
- [ ] Process restart — exit the shell/process after a nonterminal slice, open a new process, and run
  `uv run sim-pilot task show TASK_ID`.
- [ ] Resume — `uv run sim-pilot task resume TASK_ID --decision-provider scripted --iterations 1`.
- [ ] Event inspection — `uv run sim-pilot task events TASK_ID`; verify ordered append-only JSON.
- [ ] Recovery inspection — against a prepared interrupted-action fixture, run
  `uv run sim-pilot task recovery show TASK_ID`.
- [ ] Recovery resolution — run `uv run sim-pilot task recovery resolve TASK_ID RESOLUTION` using the
  resolution recommended by the inspection output; verify that the interrupted action is not
  silently retried.
- [ ] Failed task — use the prepared deterministic failure fixture and confirm `task show` explains
  the terminal reason.
- [ ] Blocked task — exhaust or deny a safe scripted plan and confirm the blocked reason is useful.

## OpenTTD Admin integration

- [ ] Doctor — `uv run sim-pilot openttd doctor`; expect version 15.3, protocol 3, loopback, and the
  selected company.
- [ ] Capabilities — `uv run sim-pilot openttd capabilities`; confirm writes are false by default.
- [ ] Observe — `uv run sim-pilot openttd observe`; confirm canonical resources and timestamps.
- [ ] Watch — `uv run sim-pilot openttd watch --count 5`; confirm only changes are emitted.
- [ ] Disabled-write rejection — with `SIM_PILOT_OPENTTD_ALLOW_WRITES` unset, run
  `uv run sim-pilot openttd action set-server-name "Rejected Test"`; expect refusal and no change.
- [ ] Server-name write — on the disposable server only, set
  `SIM_PILOT_OPENTTD_ALLOW_WRITES=1`, run `uv run sim-pilot openttd action set-server-name "Sim Pilot Founder Test"`,
  and verify before/after state.
- [ ] Stale-state rejection — use the prepared stale Admin snapshot scenario and confirm a write is
  rejected rather than applied against stale state.

## GameScript bridge

Set `SIM_PILOT_OPENTTD_GS_ENABLED=1` only after the disposable server is running the checked-in
bridge script.

- [ ] Bridge doctor — `uv run sim-pilot openttd bridge doctor`.
- [ ] Capability negotiation — `uv run sim-pilot openttd bridge capabilities`; record the fingerprint.
- [ ] Snapshot — `uv run sim-pilot openttd bridge observe`; confirm Admin and bridge identities agree.
- [ ] Reconnect — stop and restart the client process, rerun bridge doctor, and confirm sequence and
  identity handling.
- [ ] Save/load — save the disposable game, reload it, then run bridge sync and record continuity.
- [ ] Company-name write — set `SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1`, run
  `uv run sim-pilot openttd bridge action set-company-name "Sim Pilot Founder Test"`, and verify the
  fresh before/after observation.
- [ ] Duplicate command — execute the prepared duplicate-command scenario and verify one mutation
  with an idempotent repeated result.
- [ ] Conflicting duplicate — reuse a command ID with different content in the prepared scenario;
  expect deterministic rejection.
- [ ] Identity mismatch — point the client at a prepared mismatched bridge/save identity; expect a
  fail-closed result.
- [ ] Crash recovery — interrupt the prepared company-name action at its documented crash window,
  restart, inspect recovery, and verify no blind retry.

## Completion handoff

Return the filled records, including failures and low ratings. Do not repair friction while running
the checklist unless it blocks all further testing; preserve the evidence for
`docs/009-product-usability-findings.md`.

