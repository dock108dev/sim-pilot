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

---

## Persistence

Stores runtime state.

Persists

- tasks
- observations
- events
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

```text
Observe

↓

Evaluate

↓

Generate Decision

↓

Validate Policy

↓

Execute Action

↓

Observe

↓

Verify

↓

Persist

↓

Repeat
```

---

# Persistence Model

## Tasks

```text
id
status
specification
sequence
created_at
updated_at
```

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

- task storage
- event storage
- approval storage

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

- Restores runtime state after restart.
- Maintains ordered event history.

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
| OQ-004 | Simulation state serialization format | Open |
| OQ-005 | Event payload schema versioning | Open |
