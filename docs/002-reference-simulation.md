# RFC-002: Reference Simulation Specification

**Status:** Draft
**Version:** 0.1

---

# Purpose

The Reference Simulation provides a deterministic environment for validating the runtime before integrating with a production game.

Its purpose is to verify:

- Runtime execution
- Decision making
- Policy enforcement
- Progress evaluation
- Task completion
- Persistence
- Resume behavior
- Testing

The Reference Simulation is a testing environment, not a game.

It is implemented as a standalone deterministic engine under
`sim_pilot.reference_simulation`. It has no dependency on the runtime or adapter packages. The
runtime-facing adapter is a separate consumer under `sim_pilot.adapters.reference`.

---

# Goals

The simulation must:

- Be deterministic.
- Execute quickly.
- Produce repeatable results.
- Expose meaningful tradeoffs.
- Require planning.
- Support automated testing.

---

# Runtime Model

The simulation advances in discrete ticks.

Every tick executes in this order:

1. Reject progression if the simulation is paused or failed.
2. Increment the tick.
3. Progress active projects.
4. Complete finished projects.
5. Recalculate power usage.
6. Calculate population growth.
7. Calculate income.
8. Calculate recurring expenses.
9. Update cash.
10. Degrade infrastructure.
11. Recalculate derived values.
12. Evaluate simulation failure conditions.
13. Emit simulation events.

Task 2 contains no random behavior. A seed remains part of the simulation constructor for future
compatibility. Identical state, seed, and action sequence always produce identical output.

---

# Simulation State

```python
SimulationState
```

Fields

| Field | Type |
|---------|------|
| schema_version | int |
| tick | int |
| cash | float |
| debt | float |
| population | int |
| housing | int |
| power_capacity | int |
| power_usage | int |
| infrastructure | float |
| maintenance_level | float |
| income_per_tick | float |
| expense_per_tick | float |
| paused | bool |
| failed | bool |
| active_projects | list[Project] |

---

# Derived Values

Calculated every observation.

- Available Housing
- Available Power
- Net Income
- Population Growth
- Operating Margin
- Infrastructure Trend

Derived values are not persisted.

---

# Project Model

```python
Project
```

Fields

| Field | Type |
|---------|------|
| id | UUID |
| type | ProjectType |
| amount | int |
| progress | int |
| duration | int |
| remaining_ticks | int |
| total_cost | float |

---

# Project Types

- Housing
- Power

Multiple projects and duplicate project types may run concurrently. At most five projects may be
active. A project is paid in full when it starts. Housing projects take five ticks and power
projects take eight ticks. Completed projects are removed from `active_projects` immediately.

---

# Tick Processing

The ordered steps in Runtime Model are canonical. Project completion effects occur before power
usage, population growth, income, and expense calculations for that tick.

---

# Population

```text
power_usage = population
available_housing = housing - population
available_power = power_capacity - power_usage
base_growth = floor(population * 0.01)
growth = min(base_growth, available_housing, max(available_power, 0))
```

Growth is zero when infrastructure is below 40, power capacity is below power usage, housing is
not greater than population, or the simulation is paused or failed. Population never exceeds
housing or supported power capacity.

---

# Income

```text
base_income = population * 20
infrastructure_multiplier = infrastructure / 100
power_multiplier = 1.0 if power_capacity >= power_usage else 0.5
income = base_income * infrastructure_multiplier * power_multiplier
```

---

# Expenses

Recurring expense is maintenance plus debt expense. Project costs are paid at project start and are
not recurring expenses. Debt expense per tick is `debt * 0.001`.

```text
cash += income
cash -= maintenance_cost
cash -= debt_expense
```

---

# Infrastructure

Infrastructure ranges from:

```text
0.0

↓

100.0
```

Only three maintenance levels are valid:

| Level | Recurring cost | Degradation per tick |
|------:|---------------:|---------------------:|
| 0.0 | 0 | 2.0 |
| 0.5 | 2500 | 1.0 |
| 1.0 | 5000 | 0.25 |

Repair actions restore infrastructure.

If infrastructure reaches zero:

- population stops growing
- income decreases significantly

---

# Power

Power usage is proportional to population.

If demand exceeds capacity:

- population growth stops
- income decreases

---

# Housing

Housing defines maximum supported population.

Building housing increases capacity only after project completion.

---

# Debt

Loans immediately increase:

- cash
- debt

Debt produces recurring expense.

Repayment reduces:

- cash
- debt

---

# Available Actions

## Advance Time

```text
advance_time(ticks)
```

Advances the simulation.

---

## Build Housing

```text
build_housing(units)
```

Creates a housing project.

Costs `units * 1000`, paid in full when the project starts. Units must be positive.

Completes after project duration.

---

## Build Power

```text
build_power(capacity)
```

Creates a power project.

Costs `capacity * 1500`, paid in full when the project starts. Capacity must be positive.

Completes after project duration.

---

## Repair Infrastructure

```text
repair(amount)
```

Costs `amount * 2000`. Amount must be positive. The immediate effect is
`infrastructure = min(100, infrastructure + amount)`.

---

## Set Maintenance Level

```text
set_maintenance(level)
```

Adjusts recurring expense.

Higher maintenance reduces degradation.

---

## Take Loan

```text
take_loan(amount)
```

Immediately increases:

- cash
- debt

The minimum loan is 10,000, the maximum per action is 500,000, and total debt may not exceed
2,000,000.

---

## Repay Loan

```text
repay_loan(amount)
```

Reduces:

- cash
- debt

The amount must be positive and may not exceed either cash or debt.

---

## Pause

```text
pause()
```

Stops simulation progression.

---

## Resume

```text
resume()
```

Sets `paused` to false. `advance_time` is rejected while paused. `pause` is rejected when already
paused, and `resume` is rejected unless paused. Failure is terminal, so resume is rejected after
failure.

---

# Action Validation

Each action returns one of:

- Valid
- Invalid

Validation checks include:

- sufficient cash
- valid parameters
- project limits
- resource limits

Validation is deterministic and does not mutate state. All state-changing actions are rejected
after failure. While paused, `advance_time` is rejected; other valid actions may execute, including
`resume`.

Validation occurs before execution.

---

# Execution Result

Every action returns:

```python
ExecutionResult
```

Fields

- success
- state_changed
- cost
- message

Like every persisted domain object, an execution result includes `schema_version`, which defaults
to 1.

---

# Observation

Every runtime iteration receives an immutable observation.

Fields

- sequence
- timestamp
- tick
- summary
- state

Like every persisted domain object, an observation includes `schema_version`, which defaults to 1.

Observations never mutate after creation.

---

# Initial State

```text
Schema Version:       1

Tick:                 0

Cash:                 500000

Debt:                 0

Population:           500

Housing:              600

Power Capacity:       700

Power Usage:          500

Infrastructure:       90

Maintenance Level:    0.50

Paused:               False

Failed:               False
```

---

# Project Durations

| Project | Duration |
|-----------|----------|
| Housing | 5 ticks |
| Power | 8 ticks |

---

# Default Costs

| Action | Cost |
|----------|------|
| Build Housing | 1000 per unit |
| Build Power | 1500 per capacity unit |
| Repair Infrastructure | 2000 per point |
| Maintenance | 0, 2500, or 5000 per tick |
| Loan | No immediate cost |
| Repayment | Amount repaid |

---

# Completion Rules

Projects complete automatically when:

```text
remaining_ticks == 0
```

Completion immediately updates simulation state.

---

# Failure Conditions

Simulation failure occurs after a tick or action when:

- cash falls below zero
- infrastructure reaches zero
- debt exceeds 2,000,000

Failure is terminal for that simulation instance. It sets `failed` and `paused` to true. State
remains observable and all later state-changing actions are rejected.

---

# Simulation Events

`SimulationEvent` is an immutable strict model with:

- schema_version
- sequence
- tick
- type
- details

The simulation emits:

- TickAdvanced
- ProjectStarted
- ProjectCompleted
- InfrastructureChanged
- PopulationChanged
- CashChanged
- DebtChanged
- SimulationPaused
- SimulationResumed
- SimulationFailed

`SimulationFailure` is an immutable strict model containing a machine-readable `code` and a
human-readable `message`. Failure codes are `negative_cash`, `infrastructure_depleted`, and
`debt_limit_exceeded`.

---

# Deterministic Behavior

Given:

- identical seed
- identical initial state
- identical actions

The simulation must always produce identical observations and events. Fixtures under
`tests/fixtures` are canonical input states loaded directly by scenario tests.

For Task 4B, the reference adapter exposes a storage-independent snapshot containing the complete
`SimulationState`, simulation schema version, deterministic seed, and current observation
sequence. Restoration validates schema version and recreates the adapter without observing,
advancing a tick, or executing an action. The first observation after restoration continues at the
next sequence, and applying the same future actions produces the same state as uninterrupted
execution. Runtime persistence stores this snapshot data without the adapter importing persistence
or runtime modules.

---

# Test Scenarios

## Scenario A

Objective

```text
Reach $1,000,000
```

Expected

Task completes.

---

## Scenario B

Objective

```text
Maintain infrastructure above 70%
```

Expected

Repair actions occur when required.

---

## Scenario C

Constraint

```text
Loans forbidden
```

Expected

Loan actions rejected.

---

## Scenario D

Constraint

```text
Maintain $100,000 reserve
```

Expected

Spending blocked when reserve would be violated.

---

## Scenario E

Authority

```text
Maximum autonomous spend:
$50,000
```

Expected

Approval requested before expensive actions.

---

## Scenario F

Task

```text
Run until population reaches 2,000.
```

Expected

Housing and power projects are scheduled as required.

---

# Acceptance Criteria

The Reference Simulation is complete when:

- Every action is deterministic.
- Every observation is immutable.
- Every state transition is reproducible.
- Every action can be validated before execution.
- Every simulation can be recreated from an initial state and action sequence.
- Automated scenario tests produce identical results across repeated runs.

---

# Assumptions

- Single-player execution.
- Single runtime instance.
- Single active simulation.
- Fixed simulation rules during execution.
- No external dependencies.

The simulation uses numeric currency values and deterministic arithmetic. The formulas, prices,
durations, limits, and processing order in this RFC are the complete Task 2 rules.
