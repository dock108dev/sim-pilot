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

Produces the next runtime decision using:

- task specification
- current observation
- available actions
- execution history

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

The runtime depends on a decision-provider interface. Task 3 supplies a scripted implementation
that returns one decision per request and fails deterministically when exhausted. LLM providers are
out of scope.

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

## Tasks

```text
id
status
specification
sequence
created_at
updated_at
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
updated_at
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
| OQ-001 | Structured output provider implementation | Open |
| OQ-002 | SQLite ORM vs direct SQL | Open |
| OQ-003 | Prompt version storage | Open |
| OQ-004 | Simulation state serialization format | Resolved: versioned JSON |
| OQ-005 | Event payload schema versioning | Resolved: schema version 1 event records |
