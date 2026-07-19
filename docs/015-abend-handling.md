# Abend and Failure Handling

- Status: Implemented
- Date: 2026-07-19
- Scope: CLI, runtime, persistence, providers, adapter lifecycle, and OpenTTD transport cleanup

## Failure flow

Sim Pilot has no HTTP handlers, background workers, queues, schedulers, or browser error boundary.
Failures move through a local synchronous/async CLI process:

```text
CLI input
  -> provider / runtime / adapter
  -> typed boundary error or durable TaskFailed event
  -> adapter shutdown
  -> typed CLI exit code
```

Runtime events are the durable audit record. Standard-library logs add live traceback context for
unexpected exceptions. Logs intentionally identify task ID, phase, status, and exception type;
provider prompts, credentials, and complete game state are not added as logging fields.

## Implemented outcomes

### Unexpected runtime and adapter exceptions

- Severity before hardening: medium
- Risk: an exception was converted into `TaskFailed`, but the event contained only a free-form
  reason and no traceback was emitted. Initialization, iteration, and cleanup failures were harder
  to distinguish operationally.
- Current behavior: initialization and iteration exceptions emit an error log with traceback and
  persist `reason`, `error_type`, and `phase` in `TaskFailed`.
- Data integrity: the failure transition and events remain one atomic iteration.
- Persistence unavailable: `DurablePersistenceError` escapes because recording success or failure
  cannot be claimed safely.

### Adapter shutdown

- Severity before hardening: medium
- Risk: shutdown exceptions after terminal task completion were silently ignored.
- Current behavior: shutdown is still attempted on every initialized exit path. Failure while a
  task is running produces a durable `TaskFailed` with phase `adapter_shutdown`. Failure after an
  already committed completed, blocked, failed, cancelled, or approval-waiting outcome is logged
  with traceback and does not rewrite that outcome.
- Rationale: cleanup failure must be visible, but it cannot retroactively invalidate an atomic
  terminal task result.

### Codex diagnostic and temporary-directory cleanup

- Severity before hardening: medium
- Risk: an `OSError` during cleanup could replace the actual timeout, malformed JSONL, refusal, or
  structured-output failure.
- Current behavior: when a primary failure is active, the cleanup exception is logged and attached
  as an exception note; the primary typed error is preserved. When processing otherwise succeeded,
  cleanup failure remains `CodexCLITemporaryDirectoryError` or `CodexCLISchemaFileError`.
- Rationale: primary cause preservation is essential, while successful isolation still requires
  its cleanup guarantee.

### CLI failures

- Severity before hardening: low
- Risk: `error: message` made validation, provider, transport, and persistence failures difficult
  to distinguish in scripts and operator transcripts.
- Current behavior: stderr uses `error[ExceptionType]: message` and retains the established numeric
  exit-code contract.

### Alembic logging configuration

- Severity before hardening: medium
- Risk: in-process migration setup used `fileConfig`'s default behavior, which disables existing
  non-root loggers. A migration early in a CLI/test process could silence later runtime, provider,
  and adapter diagnostics.
- Current behavior: Alembic loads its console configuration with `disable_existing_loggers=False`.
  Application loggers remain active across programmatic migrations.

### SQLite transaction cleanup

- Severity before hardening: medium
- Risk: rollback or connection-close failure during a failed commit could replace the commit error,
  obscuring the operation that first placed atomic persistence at risk. A connection successfully
  opened before `begin` failed could also remain unclosed.
- Current behavior: partially opened connections are closed; rollback and close failures are logged
  and attached as exception notes without replacing the primary transaction error. A standalone
  close failure remains a typed `TransactionError`.

### OpenTTD close errors

- Severity before hardening: low
- Risk: expected connection-reset and socket-close errors were suppressed without any signal.
- Current behavior: local connection state is cleared first. Admin-quit and wait-closed failures
  remain non-fatal cleanup conditions but emit warnings with stage and exception type.
- Rationale: a peer disappearing during close is common and cannot be repaired, but repeated close
  failures must be diagnosable.

## Intentional resilience retained

- Product evaluation catches each case independently and stores `failure_category` plus a redacted,
  bounded failure message. One paid/evaluated case must not erase the remaining evidence.
- OpenAI retries a typed transient failure once. Authentication, semantic invalidity, refusal, and
  non-transient failures do not retry.
- Codex subprocess execution does not retry because a repeated hosted call could consume allowance
  and produce an ambiguous duplicate decision.
- A broken stdin pipe after the Codex child exits is ignored; terminal status, bounded stderr, and
  JSONL parsing determine the actual result.
- OpenTTD `BridgeCommandError` becomes a failed `ExecutionResult`. The runtime persists and verifies
  that result rather than treating an expected remote command rejection as a process abend.
- OpenTTD connection/setup catches broadly only to close partially initialized transport and then
  re-raises the original exception.
- Repository `latest` methods return `None` for an absent optional record. Corrupt payloads and SQL
  failures remain typed errors rather than empty defaults.
- Crash-injection uses `BaseException` deliberately so production exception handling cannot convert
  a simulated process death into a normal task failure.

## Operator response

1. Record the CLI exception type, exit code, task ID, and failure phase.
2. Run `task show` and `task events`; confirm whether `TaskFailed` committed.
3. If persistence/reconstruction failed, preserve the database and sidecars before attempting
   repair.
4. If an unresolved action attempt exists, inspect and reconcile it. Never automatically rerun the
   interrupted action.
5. For Codex failures, preserve debug output only through the explicit diagnostic flags and review
   owner-only artifacts locally.
6. For repeated OpenTTD close warnings, verify the loopback server lifecycle and whether the server
   exited before the client cleanup handshake.

## Remaining risks

- Logging uses the host process's standard-library logging configuration. A packaged daemon or
  remote service will need an explicit structured sink, retention policy, redaction policy, and
  alert thresholds.
- Event failure reasons retain exception messages for local diagnosis. Before multi-user or remote
  deployment, define a public-safe error taxonomy separate from private operator detail.
- SQLite and the runtime assume one active runtime. Multi-process coordination needs a separate
  ownership/locking design rather than broader exception suppression or automatic retries.
