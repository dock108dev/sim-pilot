# RFC-001: Milestone 1 Runtime Design

**Status:** Draft
**Version:** 0.1

---

# Purpose

Milestone 1 establishes the core runtime responsible for executing delegated tasks against a simulation.

The runtime accepts a structured task, observes simulation state, determines the next action, validates it, executes it, verifies the result, and repeats until the task completes or requires user intervention.

This milestone delivers the execution engine and validates the architecture using a deterministic reference simulation.

---

# Objectives

## Functional

- Execute delegated tasks one action at a time.
- Observe simulation state.
- Select valid actions.
- Validate actions against task policy.
- Execute actions through a simulation adapter.
- Verify execution results.
- Persist execution history.
- Support interruption and resume.

## Technical

- Strongly typed domain model.
- Deterministic execution loop.
- Modular runtime components.
- Complete automated test coverage for runtime behavior.

---

# Architecture

```text
                    Task

                     │

                     ▼

           Runtime Engine

     ┌─────────────────────────┐
     │ Progress Evaluator      │
     │ Decision Engine         │
     │ Policy Engine           │
     │ Persistence             │
     └─────────────────────────┘

                     │

                     ▼

          Reference Adapter

                     │

                     ▼

          Reference Simulation
```

---

# Runtime Lifecycle

```text
Create Task

↓

Compile Task

↓

Initialize Adapter

↓

Observe State

↓

Evaluate Progress

↓

Generate Decision

↓

Validate Policy

↓

Execute Action

↓

Observe State

↓

Verify Result

↓

Continue
Complete
Blocked
Approval Required
```

---

# Repository Structure

```text
sim-pilot/

├── docs/
├── src/
│   └── sim_pilot/
│       ├── cli.py
│       ├── config.py
│       │
│       ├── runtime/
│       ├── domain/
│       ├── adapters/
│       │   └── reference/
│       │       └── adapter.py
│       ├── reference_simulation/
│       │   ├── state.py
│       │   ├── economy.py
│       │   ├── projects.py
│       │   ├── tick.py
│       │   ├── actions.py
│       │   ├── validation.py
│       │   └── simulation.py
│       ├── llm/
│       ├── persistence/
│       └── logging/
│
├── tests/
└── data/
```

---

# Runtime Components

## Runtime Engine

Coordinates execution of delegated tasks.

Responsibilities

- lifecycle management
- execution loop
- orchestration
- resume
- shutdown

---

## Instruction Compiler

Converts natural language into a structured task specification.

Task 5 names this component the **Intent Compiler**. It translates user intent but never chooses
runtime actions. Its provider-independent pipeline is:

```text
Instruction -> CompilerProvider -> CompilerProviderResult -> CompilerResponse
            -> Deterministic Validation -> CompilerReport -> TaskSpecification
```

`CompilerReport` records prompt version, validation status, assumptions, warnings, unsupported
requests, ambiguities, and structured validation errors. Validation statuses are `valid`,
`clarification_required`, `unsupported`, and `invalid`. Only `valid` results expose a
`TaskSpecification` to the runtime.

The provider response is strict structured output. Provider prose is never parsed. Each provider
returns a `CompilerProviderResult` containing that `CompilerResponse` plus provider name, optional
model identifier, and optional token usage. This telemetry envelope does not alter compilation
semantics or the frozen `TaskSpecification` contract.

The OpenAI implementation uses provider-native Pydantic structured output and is the only module
allowed to import the OpenAI SDK. Hosted access is never selected implicitly: the CLI defaults to
`NoProviderConfigured`, and `--provider openai` is required for an OpenAI request. Codex CLI or
ChatGPT login state is development-tool authentication and is not consumed as runtime API
authentication. Scripted providers cover automated tests; live provider tests are opt-in and never
required by CI.

An opt-in `RecordingCompilerProvider` decorates any configured provider and writes one atomic JSON
record per successful request. Records contain the original instruction, complete prompt, prompt
version, structured response, latency, provider, model, and token usage when available. Because
instructions and prompts may contain sensitive data, recording is disabled by default and requires
an explicit local output directory.

Prompt version `intent-compiler-v2` defines all supported objective and constraint contracts,
authority fields, and unsupported behavior. The compiler receives an environment capability
catalog: reference-simulation capabilities remain the default, while OpenTTD capabilities are
selected explicitly and are never added globally to the reference prompt. A semantic prompt change
requires a new version and golden-fixture review. The compiler never invents a missing threshold or
runtime capability.

`run_until` normally compares numeric resources with `above` or `below`. An environment catalog may
declare a string resource and allow `direction="equal"` with an exact string target. Task 6C uses
this only for the observed OpenTTD `server_name` resource. The evaluator resolves resources from
either the canonical top-level reference state or an adapter's typed `resources` projection.

Supported compiler resources are `tick`, `cash`, `debt`, `population`, `housing`,
`power_capacity`, `power_usage`, `infrastructure`, `maintenance_level`, `income_per_tick`, and
`expense_per_tick`. Supported project types are `housing` and `power`. Supported action names are
the nine actions in RFC-002.

Deterministic validation rejects invalid parameter shapes, resources, actions, project types,
thresholds, stop conditions, impossible bounded-resource objectives, mutually exclusive allowed
rules, allowed/forbidden conflicts, approval/forbidden conflicts, and objective/resource-floor
contradictions. Material ambiguity requires clarification. Broad strategy requests such as winning,
optimizing, or making smart decisions are unsupported.

Input

```text
Run until cash reaches $1M.

Do not take loans.

Pause if infrastructure health drops below 40%.
```

Output

```text
TaskSpecification
```

---

## Decision Engine

Produces the next runtime decision through a provider-independent boundary. The contract is:

```text
DecisionProvider.decide(DecisionContext) -> DecisionProviderResult
```

`DecisionProviderResult` contains exactly one strict `Decision` plus shared provider metadata. The
provider never executes actions, queries persistence, contacts an adapter, evaluates policy,
approves actions, or determines final completion.

`DecisionContext` contains:

- task identifier and complete task specification
- current and previous observation
- exact advertised action and parameter schemas
- bounded recent relevant event summaries
- accumulated spend and remaining authority
- forbidden, allowed, rejected, and denied action summaries
- previous action, execution result, and verification when available
- durable safeguard counters
- deterministic evaluator progress

The runtime constructs this context through a pure projector. It retains at most 20 relevant events
and 65,536 serialized bytes by default, removes oldest relevant events first, and rejects an
oversized base context. Canonical JSON uses sorted keys and compact separators, so identical inputs
serialize identically. Providers do not receive raw repository rows or unbounded event streams.

The model-backed prompt is versioned as `decision-provider-v1`. It permits only one decision and
only advertised actions. Provider output is validated for decision/action consistency, action
existence, exact parameter names, parameter types and bounds, finite non-negative estimated cost,
action fingerprinting, and evaluator-confirmed completion. Invalid output is never materially
repaired.

Decision provider failures are typed as authentication, timeout, rate limit, unavailable,
malformed structured output, semantic validation, context too large, refusal, empty response,
unconfigured provider, or recording failure. OpenAI transient failures retry once; semantic
invalidity does not retry. Exhausted hosted failures atomically record `DecisionProviderFailed` and
`TaskFailed`, then follow normal adapter shutdown. Scripted exhaustion retains its existing blocked
behavior.

CLI composition defaults to no decision provider. Hosted execution requires explicit
`--decision-provider openai`; environment variables configure a selected provider but never select
one. Provider metadata in `DecisionGenerated` includes provider, model, request ID when available,
token usage, latency, prompt version, and validation result. Full prompts are not persisted.

Returns

```text
Decision
```

---

## Policy Engine

Determines whether an action may execute.

Responsibilities

- authority validation
- constraint validation
- approval requirements
- action rejection

Returns

```text
PolicyDecision
```

---

## Progress Evaluator

Evaluates task status.

Possible outcomes

- Running
- Completed
- Blocked
- WaitingForApproval

The evaluator has final authority over objective completion. A decision provider may suggest
`Complete`, but the runtime completes only after the evaluator confirms the objective from an
observation. Premature completion claims are rejected.

Task 3 objective parameter contracts are:

- `ReachResource`: `resource`, numeric `target`
- `MaintainResource`: `resource`, numeric `target`, `direction` (`above` or `below`)
- `RunUntil`: `resource`, numeric `target`, `direction` (`above` or `below`)
- `CompleteProject`: `project_type`; complete when no matching active project remains

Task 3 stop conditions use the deterministic string grammar
`<resource> <operator> <number>`, where operator is `>`, `>=`, `<`, `<=`, or `==`.

---

## Persistence

Stores runtime state.

Task 3 uses an append-only in-memory event store behind a storage interface. The runtime depends on
that interface rather than a database implementation. Task 4 adds SQLite durability behind the
same interface without changing runtime behavior.

The Task 3 store guarantees:

- immutable, versioned events
- task-scoped event streams
- monotonically increasing sequence numbers
- append-only writes with no update, deletion, or out-of-order insertion
- deterministic ordered reads and replay

In-memory storage does not survive process termination. Restart boundaries are exercised by
constructing a new runtime over an existing populated store instance. Process-level durability,
SQLite schema design, transactions, and migrations are Task 4 concerns.

Task 4 uses current-state snapshots plus the complete append-only event log. It does not require
event replay to reconstruct current state. Restart loads the latest task and simulation snapshots,
then uses the event stream for audit and diagnostics.

Runtime persistence ownership is expressed through `TaskRepository`, `EventRepository`,
`ApprovalRepository`, and `SimulationRepository`. Runtime code depends only on those interfaces.
SQLite connections, SQL, tables, mappings, and Alembic integration remain inside the persistence
package. A unit-of-work boundary coordinates the repositories.

Everything durably representing one runtime iteration commits in one transaction: task changes,
simulation checkpoint, approval changes, and appended events either all commit or none commit.
Adapter execution itself is external to SQLite; Task 4C defines reconciliation when a crash occurs
after the action side effect but before the checkpoint transaction commits.

Alembic owns the SQLite schema from its initial revision onward. Application startup does not create
or modify schema outside migrations.

Persists

- tasks
- current simulation snapshots
- append-only events and observations
- approvals

---

# Domain Model

All domain models include:

- schema_version (defaults to 1)

`TaskSpecification`, `Observation`, `Action`, and `Decision` are public runtime interfaces. Any
field or semantic change to those models requires a corresponding RFC update.

## Task

Fields

- id
- status
- specification
- sequence
- total_spend
- created_at
- updated_at

Task lifecycle statuses are `pending`, `running`, `waiting_for_approval`, `completed`, `blocked`,
`failed`, and `cancelled`. Valid transitions are:

- pending to running or cancelled
- running to completed, blocked, failed, waiting_for_approval, or cancelled
- waiting_for_approval to running, blocked, or cancelled

Terminal statuses do not transition.

---

## TaskSpecification

Contains

- adapter_type (`reference` by default; persisted so restart composition is unambiguous)
- objective
- constraints
- authority
- notifications
- stop_conditions

---

## Objective

Supported types

- ReachResource
- MaintainResource
- CompleteProject
- RunUntil

---

## Constraint

Supported types

- MaximumSpend
- MinimumReserve
- AllowedAction
- ForbiddenAction
- ResourceFloor

Task 3 constraint parameter contracts are:

- `ForbiddenAction`: `action`
- `AllowedAction`: `action` or `actions`
- `MaximumSpend`: numeric `amount`, enforced against accumulated spend plus proposed cost
- `MinimumReserve`: numeric `amount`, enforced against cash after proposed cost
- `ResourceFloor`: `resource` and numeric `floor`

---

## Authority

Defines autonomous execution limits.

Fields

- maximum_single_spend
- maximum_total_spend
- approval_actions
- forbidden_actions

---

## Observation

Immutable snapshot of simulation state.

Fields

- sequence
- timestamp
- tick
- summary
- state

---

## Action

Fields

- type
- parameters
- expected_effect
- estimated_cost

---

## Decision

Supported decisions

- Execute
- Wait
- Complete
- ApprovalRequired
- Blocked

---

# Simulation Adapter

The deterministic reference simulation is a standalone engine. Its state transitions, economic
rules, project progression, actions, and validation do not depend on the runtime or adapter
packages. The reference adapter consumes that engine and translates between its API and the common
runtime domain contract.

Dependency direction is:

```text
CLI -> Runtime -> Domain <- Adapter -> Reference Simulation
```

Adapters must not import runtime modules. The reference simulation must not import adapter or
runtime modules.

```python
class SimulationAdapter(Protocol):

    async def initialize(self) -> None

    async def observe(self) -> Observation

    async def available_actions(
        self
    ) -> list[ActionDefinition]

    async def validate(
        self,
        action: Action
    ) -> ValidationResult

    async def execute(
        self,
        action: Action
    ) -> ExecutionResult

    async def shutdown(self) -> None
```

---

# Runtime Execution Sequence

1. Transition the task to running.
2. Initialize the adapter.
3. Observe and append `ObservationRecorded`.
4. Evaluate the objective and stop conditions.
5. Complete or block if evaluation is terminal.
6. Request exactly one decision from the decision provider.
7. Validate decision consistency.
8. Ask the adapter to validate an action, when present.
9. Evaluate task constraints and authority through the policy engine.
10. Reject, suspend for approval, or execute one action.
11. Append the execution result and observe again.
12. Verify the observed effect and append verification.
13. Update accumulated spend only after verified success.
14. Repeat until terminal or suspended.
15. Shut down the adapter on every exit path.

The runtime depends only on the decision-provider interface. The scripted implementation returns
one decision per request and fails deterministically when exhausted. Task 6A adds an OpenAI
implementation behind the same interface without changing the execution sequence.

Policy evaluation and adapter validation do not mutate state. The adapter owns simulation-specific
validity; the policy engine owns constraints and authority. `maximum_single_spend` is the autonomous
approval threshold. `maximum_total_spend` is a hard cumulative ceiling.

After execution, verification compares the prior observation, proposed action, reported result,
validated cost, and resulting observation. A false success, unexpected mutation on failure,
incorrect cost, missing required state change, or incorrect reference-action effect fails the task.

Approval suspends execution in `waiting_for_approval` and shuts down the adapter. Granting approval
records `ApprovalGranted` and permits that exact action once on resume. Denial records
`ApprovalDenied` and blocks the task. Approval state remains in memory for Task 3.

Runtime safeguard defaults are:

- maximum iterations: 100
- maximum consecutive failures: 3
- repeated identical action against identical state: 3
- repeated state: 3
- false completion: reject and continue until another safeguard or decision terminates execution

---

# Persistence Model

Task 4 durable persistence is delivered incrementally:

- Task 4A: schema, repository implementations, Alembic migrations, and atomic transaction tests;
  no runtime changes
- Task 4B: simulation checkpointing, restoration, and task resume; no CLI
- Task 4C: crash recovery, approval recovery, restart integration tests, and CLI wiring

Task 4C journals the external action boundary through append-only events. An action is prepared and
assigned a stable identifier before execution starts. A successful completion transaction contains
the execution result, resulting observation, verification, task and spend updates, simulation
checkpoint, and attempt completion. The runtime does not claim exactly-once execution because the
adapter side effect is outside SQLite.

On restart, a prepared attempt that never entered execution is safely retired as not executed. An
attempt that entered execution without a committed checkpoint suspends further actions and requires
reconciliation. Task status remains `running`; the unresolved attempt is the durable
recovery-required marker. Reconciliation outcomes are definitely not executed, definitely executed,
inferable, ambiguous, and adapter unavailable. Ambiguous or unavailable attempts are never retried
automatically. Operator resolutions are accept current state, mark executed, mark not executed,
abandon, and restore the prior checkpoint.

Task 4A uses SQLAlchemy Core for typed SQL construction and explicit transaction ownership. It does
not expose ORM sessions or SQLAlchemy row models through runtime-facing interfaces. SQLite is
accessed through Python's database driver beneath SQLAlchemy; no external database service or
asynchronous driver is required.

The storage-independent repository operations are:

- `TaskRepository`: `create`, `get`, `update`, and `list`
- `EventRepository`: `append`, `append_many`, `list_for_task`, `latest`, and `get_by_sequence`
- `ApprovalRepository`: `create`, `get`, `get_pending_for_task`, `update`, and `list_for_task`
- `SimulationRepository`: `save`, `latest`, and `get_by_runtime_sequence`

Repository failures cross the boundary only as typed persistence errors: record not found,
duplicate record, sequence conflict, stale update, transaction failure, unsupported schema
version, or invalid persisted payload. SQLite and SQLAlchemy exceptions do not cross that boundary.

`UnitOfWork` exposes all four repositories and supports explicit `begin`, `commit`, `rollback`, and
context-manager use. A context commits on successful exit and deterministically rolls back on an
exception. Task 4A supplies transactional in-memory and SQLite implementations that satisfy the
same repository contract tests.

Task 4B integrates this boundary into the runtime. Task creation is one transaction containing the
pending task snapshot and `TaskCreated`. Adapter initialization is followed by one transaction
containing `TaskStarted`, the initial observation, the running task snapshot, and the initial
simulation checkpoint. Each later runtime iteration buffers its evaluation, decision, policy,
execution, observation, verification, lifecycle, and approval events and commits them with the
updated task and optional checkpoint. No task sequence, spend, approval, event, or checkpoint
advances if that transaction fails. A storage-independent `DurablePersistenceError` reports the
rollback. The external adapter action remains outside the database transaction; Task 4C owns
reconciliation if that side effect succeeds before persistence fails.

Checkpoint cadence is:

- after adapter initialization and the first observation
- after every successfully verified state-changing action
- after pause and resume, which are state-changing actions
- on terminal transition when an initialized simulation checkpoint exists
- not for evaluation-only, policy-only, approval-only, or verified no-change iterations

A checkpoint retains simulation state and schema, tick, runtime sequence, adapter type and schema,
adapter observation sequence, and deterministic seed. A no-change action can produce a newer
observation without duplicating state; reconstruction obtains that observation sequence from the
event stream while loading simulation state from the latest checkpoint.

Runtime safeguard state is stored with the current task snapshot: total iteration count,
consecutive failures, repeated-action and repeated-state counts and fingerprints, rejected-action
count, and any approved-once action plus its approval identifier. The event stream remains the
audit source for decisions and rejection history; those payloads are not duplicated in the task
snapshot.

Reconstruction loads the task snapshot, complete ordered event stream, approval history, and
latest checkpoint in one read unit of work. It rejects non-contiguous events, task/event sequence
mismatch, a checkpoint ahead of the task, checkpoint state/tick/schema mismatch, an observation
that disagrees with checkpoint state, incompatible approval/status combinations, incomplete
approved-once identity, and cancellation/status mismatch. Reconstruction never executes an
adapter action.

Resume behavior by status is:

- `pending`: initialize a new adapter and start normally
- `running`: restore the adapter from the latest committed checkpoint and continue
- `waiting_for_approval` with a pending request: return without restoring or executing an adapter
- `waiting_for_approval` after approval: restore, transition to running, and authorize that exact
  action once
- `completed`, `blocked`, `failed`, or `cancelled`: return the persisted terminal outcome without
  adapter initialization or execution

Denial atomically resolves the approval, appends `ApprovalDenied` and `TaskBlocked`, and persists
the blocked task. Cancellation atomically persists cancellation intent, cancelled status, and
`TaskCancelled`. A task cancelled before adapter initialization has no fabricated simulation
checkpoint.

## Tasks

```text
id
status
specification
sequence
created_at
updated_at
cancel_requested
```

Tasks store the latest lifecycle snapshot and accumulated spend. Historical transitions remain in
the event stream.

---

## Simulation Snapshots

```text
task_id
schema_version
state
tick
runtime_sequence
simulation_schema_version
created_at
```

The latest versioned simulation state is loaded directly on restart.

---

## Events

```text
id
task_id
sequence
event_type
payload
created_at
```

Every durable table has a stable record identifier and `schema_version`. Timestamps are canonical
timezone-aware UTC values. Task snapshots retain status, accumulated spend, current runtime
sequence, and cancellation intent. Event sequences begin at one and append exactly in order.
Simulation checkpoints are immutable per runtime sequence and reject any checkpoint at or below
the latest stored sequence. Checkpoint lookup is by runtime sequence.

The initial Alembic revision creates `tasks`, `events`, `approvals`, and
`simulation_checkpoints`. Foreign keys associate every event, approval, and checkpoint with a
task. Unique and lookup indexes enforce task-scoped event ordering, pending approval identity, and
latest-checkpoint retrieval. A pending duplicate is defined as the same canonical action for the
same task; approval history remains retained after resolution.

For a given task, `sequence` starts at 1 and each append must use the next sequence exactly. Event
payloads and stored event records include `schema_version`. Reading a stream always returns events
in ascending sequence order.

---

## Approvals

```text
id
task_id
status
action
created_at
resolved_at
```

---

# Event Types

- TaskCreated
- TaskStarted
- ObservationRecorded
- DecisionGenerated
- DecisionProviderFailed
- PolicyValidated
- ActionExecuted
- ActionRejected
- ApprovalRequested
- ApprovalGranted
- ApprovalDenied
- TaskCompleted
- TaskBlocked
- TaskFailed
- EvaluationRecorded
- VerificationRecorded
- TaskCancelled

---

# Runtime Loop

```python
initialize()

while task.running:

    observation = adapter.observe()

    evaluation = evaluator.evaluate(
        task,
        observation
    )

    if evaluation.complete:
        complete()
        break

    decision = decision_engine.decide(
        task,
        observation
    )

    policy = policy_engine.validate(
        decision.action
    )

    if policy.requires_approval:
        request_approval()
        break

    result = adapter.execute(
        decision.action
    )

    verify(result)

    persist(result)
```

---

# Logging

Every execution step generates a runtime event.

Minimum fields

```text
timestamp
task_id
sequence
component
event
duration
```

---

# Command Line Interface

```bash
sim create
sim run
sim show
sim events
sim approve
sim deny
sim resume
sim cancel
```

---

# Testing

## Unit Tests

- compiler
- policy engine
- evaluator
- persistence
- runtime

---

## Adapter Tests

Validate

- initialize
- observe
- validate
- execute
- shutdown

---

## Runtime Scenarios

- successful completion
- approval workflow
- policy rejection
- blocked execution
- resume after restart
- repeated execution
- failed execution

---

# Milestone Deliverables

## Runtime

- execution engine
- task lifecycle
- execution loop

## Compiler

- structured task generation

## Policy

- constraint enforcement
- authority validation

## Persistence

- append-only in-memory event store in Task 3
- storage interface and replay boundary
- SQLite task, event, and approval storage in Task 4

## Adapter

- reference implementation

## CLI

- task management commands

## Testing

- unit tests
- integration tests
- scenario tests

---

# Acceptance Criteria

## Runtime

- Executes one action per iteration.
- Supports interruption and resume.
- Persists execution history.

## Compiler

- Produces valid task specifications.

## Policy

- Rejects invalid actions.
- Enforces authority limits.

## Adapter

- Exposes the standard adapter contract.

## Evaluator

- Correctly identifies completion.
- Correctly identifies blocked execution.

## Persistence

- Restores runtime state from an existing event stream.
- Maintains immutable, ordered event history.
- Allows SQLite to replace the in-memory implementation without runtime behavior changes.

---

# Assumptions

- Runtime executes a single task at a time.
- A single simulation adapter is active during execution.
- The reference simulation provides deterministic behavior for testing.
- Structured model output is available from the selected LLM provider.

---

# Open Questions

| ID | Topic | Status |
|----|-------|--------|
| OQ-001 | Structured output provider implementation | Resolved: provider-native Pydantic structured output |
| OQ-002 | SQLite ORM vs direct SQL | Resolved: SQLAlchemy Core with explicit transactions |
| OQ-003 | Prompt version storage | Resolved: version constant recorded in every CompilerReport |
| OQ-004 | Simulation state serialization format | Resolved: versioned JSON |
| OQ-005 | Event payload schema versioning | Resolved: schema version 1 event records |
| OQ-006 | Checkpoint cadence | Resolved: initial, verified state change, and initialized terminal |
| OQ-007 | Safeguard recovery | Resolved: minimal counters/fingerprints stored on task snapshot |
| OQ-008 | Default compiler provider | Resolved: none; hosted access requires `--provider openai` |
| OQ-009 | Compiler request telemetry | Resolved: typed result envelope plus opt-in atomic JSON recorder |
| OQ-010 | Runtime decision provider | Resolved: bounded context plus explicit scripted/OpenAI/unconfigured providers |
| OQ-011 | Decision provider recording | Resolved: opt-in redacted atomic JSON; recording failure blocks execution |
