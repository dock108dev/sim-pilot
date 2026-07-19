# Security Hardening Review

- Status: Implemented
- Date: 2026-07-19
- Scope: current local CLI runtime, providers, SQLite persistence, OpenTTD integrations, and CI

## Security model and trust boundaries

Sim Pilot is a local Python/Typer CLI. It has no HTTP server, browser frontend, public or admin API,
session, user account, multi-tenant role, upload endpoint, webhook, queue, scheduler, or background
worker. Web headers, cookies, CORS, CSRF, route authorization, rate limiting, and browser XSS are
therefore outside the current attack surface.

The material boundaries are:

1. Local instructions, specification files, CLI options, environment variables, and persisted
   SQLite content enter typed Pydantic and repository boundaries.
2. Hosted OpenAI and Codex providers receive task/game context. Their structured responses are
   untrusted until strict schema and deterministic semantic validation complete.
3. `codex exec` is a local subprocess using the signed-in user's Codex credentials. It runs in an
   empty owner-only directory with ignored configuration/rules, a read-only sandbox, disabled shell
   tool, approval policy `never`, bounded streams/time, and a small environment allowlist.
4. SQLite stores task specifications, lifecycle events, observations, approvals, and checkpoints.
   The runtime reaches it only through repository/unit-of-work interfaces and atomic transactions.
5. OpenTTD Admin Network authentication is plaintext by protocol design. Configuration requires
   every resolved address to be loopback. Writes additionally require explicit feature flags,
   deterministic validation, action verification, and duplicate/recovery controls.
6. Explicit compiler, decision, debug, and evaluation recordings may contain user instructions or
   game state. Their directories/files use owner-only permissions and they are ignored by Git.
7. GitHub Actions installs locked Python dependencies and two third-party actions. Workflow token
   permission is read-only and action revisions are immutable.

## Findings

### SH-001: Codex shell capability remained available

- Category: subprocess isolation / prompt injection
- Affected area: `provider_support.codex_cli`
- Severity: medium
- Confidence: high
- Why it matters: task instructions and observed game state are model input. A successful prompt
  injection should not gain a general command-execution tool, even inside a read-only sandbox.
- Realistic scenario: malicious text in an instruction or observed name asks the model to invoke a
  shell and inspect local readable files reachable by the signed-in CLI process.
- Evidence: the command selected `--sandbox read-only` but did not disable the CLI's enabled-by-
  default `shell_tool`; the installed CLI advertises `--disable <FEATURE>` and `shell_tool`.
- Fix: require feature-disable capability and invoke `codex exec --disable shell_tool`. Tests assert
  both capability failure and command composition.
- Status: fixed

### SH-002: SQLite artifacts inherited group/world-readable modes

- Category: data protection / local storage
- Affected area: SQLite engine and Alembic migration paths
- Severity: low
- Confidence: high
- Why it matters: task text, observations, approvals, and event history can be sensitive local data.
- Realistic scenario: another local OS account reads a database or WAL file created under a normal
  `022` umask in a traversable directory.
- Evidence: a clean migration and WAL transaction produced mode `0644` for the database, `-wal`,
  and `-shm` artifacts on the development machine.
- Fix: application and raw Alembic paths create/harden the database and known rollback/WAL sidecars
  to mode `0600`; connection, commit, and rollback hooks reapply the invariant. Tests cover both
  programmatic and raw Alembic paths.
- Status: fixed

### SH-003: CI actions used mutable major-version references

- Category: dependencies and supply chain
- Affected area: `.github/workflows/checks.yml`
- Severity: medium
- Confidence: high
- Why it matters: a moved or compromised tag can change code executed with the workflow token.
- Realistic scenario: upstream tag mutation causes unreviewed action code to run on a push or pull
  request.
- Evidence: the workflow referenced `actions/checkout@v4` and `astral-sh/setup-uv@v7`.
- Fix: pin both actions to the commits currently resolved by their upstream tags while retaining
  version comments. The workflow already limits token permissions to `contents: read`.
- Status: fixed

### SH-004: OpenTTD connection invariants relied on `assert`

- Category: input/transport robustness
- Affected area: OpenTTD Admin Network client
- Severity: low
- Confidence: high
- Why it matters: Python removes assertions under optimized execution, so transport state checks
  should not depend on them.
- Realistic scenario: a disconnected client reaches a packet read/write under `python -O`, producing
  an unintended attribute failure instead of the typed fail-closed transport error.
- Evidence: `_send` and `_read_packet` asserted reader/writer presence after the connection check.
- Fix: use explicit `None` checks and `OpenTTDDisconnectedError` before I/O.
- Status: fixed

### SH-005: OpenTTD Admin credentials use plaintext transport

- Category: secrets and transport
- Affected area: OpenTTD Admin Network
- Severity: medium if exposed beyond loopback; low under the enforced deployment model
- Confidence: high
- Why it matters: the upstream protocol does not encrypt its password exchange.
- Realistic scenario: a remote or shared-network connection exposes the credential to network
  observers.
- Evidence: the protocol sends the configured password in `ADMIN_JOIN`; the configuration validator
  rejects hosts resolving to any non-loopback address.
- Control/rationale: retain loopback-only validation, `SecretStr`, environment configuration, and
  disposable-server guidance. Remote deployment would require an authenticated encrypted tunnel
  and a new architecture decision.
- Status: accepted for the local-only product boundary

### SH-006: Opt-in recordings retain sensitive semantic input

- Category: privacy and retention
- Affected area: compiler/decision/evaluation/debug recordings
- Severity: low
- Confidence: high
- Why it matters: explicit recordings can contain instructions, game state, and provider telemetry.
- Realistic scenario: an operator shares or retains a recording directory without reviewing it.
- Evidence: recording models intentionally contain prompts/context; README already identifies that
  behavior. Files are atomic and mode `0600`, directories are mode `0700`, and paths are ignored.
- Control/rationale: recording remains explicit because it is needed for local regression diagnosis.
  Operators own retention and deletion; no background upload exists.
- Status: accepted

### SH-007: Security scanners are not enforced in CI

- Category: dependency/static assurance
- Affected area: continuous integration
- Severity: informational
- Confidence: high
- Why it matters: lockfile review alone does not continuously flag newly disclosed dependency
  vulnerabilities or newly introduced risky code patterns.
- Evidence: CI runs Ruff, Pyright, and pytest only. This review ran Bandit and pip-audit manually.
- Recommended follow-up: decide on scanner ownership, update cadence, false-positive policy, and
  failure thresholds; then add pinned, reproducible Bandit and dependency-audit jobs or equivalent
  repository security services.
- Status: deferred; needs operational policy

## Intentional safe patterns verified

- SQLAlchemy Core uses bound values for dynamic data; no dynamic SQL execution path was found. A
  Bandit `B608` result points at a JSON-schema prompt string, not SQL, and is a false positive.
- Subprocess calls use argument lists with no shell. The Bandit subprocess findings identify the
  expected Codex capability probe; its executable and arguments are constrained.
- Provider output uses strict Pydantic models and deterministic post-validation. Automated tests use
  scripted providers, and hosted calls are explicit.
- OpenTTD packets are size-bounded, time-bounded, version checked, and restricted to loopback.
- No hardcoded credential, tracked database, private key, or environment-secret file was found.
- Action fingerprints, append-only event sequencing, atomic iteration persistence, post-action
  observation, and reconciliation constrain duplicate/replay behavior.

## Manual validation and remaining roadmap

Priority order:

1. Decide whether CI should fail on dependency/static scanner findings and add reproducible pinned
   checks with a documented triage policy.
2. Define a retention/deletion policy before recordings become a user-facing feature.
3. If Sim Pilot ever gains a remote service, design authentication, authorization, tenant isolation,
   transport encryption, rate limits, audit logs, and secret storage before exposing any endpoint.
4. If OpenTTD moves beyond loopback, require an encrypted authenticated tunnel and formally revisit
   ADR-011; never relax the current validator alone.
5. Periodically re-run a live Codex compatibility check because CLI flags and telemetry are an
   external versioned boundary. Live checks remain opt-in because they consume account allowance.

The review's package audit found no known vulnerabilities in the installed locked environment.
Bandit found no high-severity issue; its remaining subprocess findings describe the intentional
non-shell Codex probe, and its prompt-string SQL warning is not an executable query.
