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

Every tick:

1. Active projects progress.
2. Population changes.
3. Resources are consumed.
4. Income is calculated.
5. Expenses are deducted.
6. Infrastructure degrades.
7. Simulation state is updated.

No randomness is introduced unless a deterministic seed is supplied.

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
| progress | float |
| duration | int |
| remaining_ticks | int |
| total_cost | float |

---

# Project Types

- Housing
- Power
- Infrastructure

---

# Tick Processing

Each simulation tick executes in the following order.

```text
Advance Tick

↓

Progress Projects

↓

Complete Finished Projects

↓

Calculate Population Growth

↓

Calculate Income

↓

Calculate Expenses

↓

Update Cash

↓

Update Infrastructure

↓

Recalculate Derived Values
```

---

# Population

Population growth depends on:

- available housing
- available power
- infrastructure health

Growth stops if:

- housing is exhausted
- power is exhausted
- infrastructure falls below minimum operating threshold

Population never exceeds housing capacity.

---

# Income

Income is calculated as:

```text
population × income_per_citizen
```

Income decreases when:

- infrastructure declines
- power shortages occur

---

# Expenses

Expenses include:

- maintenance
- project costs
- debt payments

Expenses are deducted every tick.

---

# Infrastructure

Infrastructure ranges from:

```text
0.0

↓

100.0
```

Infrastructure naturally degrades every tick.

Maintenance slows degradation.

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

Consumes cash.

Completes after project duration.

---

## Build Power

```text
build_power(capacity)
```

Creates a power project.

Consumes cash.

Completes after project duration.

---

## Repair Infrastructure

```text
repair(amount)
```

Consumes cash.

Immediately restores infrastructure.

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

---

## Repay Loan

```text
repay_loan(amount)
```

Reduces:

- cash
- debt

---

## Pause

```text
pause()
```

Stops simulation progression.

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
```

---

# Project Durations

| Project | Duration |
|-----------|----------|
| Housing | 5 ticks |
| Power | 8 ticks |
| Infrastructure | Immediate |

---

# Default Costs

| Action | Cost |
|----------|------|
| Build Housing | 100000 |
| Build Power | 150000 |
| Repair Infrastructure | Variable |
| Maintenance | Recurring |
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

Simulation failure occurs when:

- cash falls below zero
- infrastructure reaches zero
- debt exceeds configured limit

Failure state remains observable.

The runtime determines whether failure ends the current task.

---

# Simulation Events

The simulation emits:

- TickAdvanced
- ProjectStarted
- ProjectCompleted
- InfrastructureChanged
- PopulationChanged
- CashChanged
- DebtChanged
- SimulationPaused

---

# Deterministic Behavior

Given:

- identical seed
- identical initial state
- identical actions

The simulation must always produce identical observations.

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

currency_unit: integer

income_per_citizen_per_tick: 100

power_usage_per_citizen: 1

base_population_growth_per_tick: 10

infrastructure_degradation_per_tick: 1

maintenance_cost_per_level_per_tick: 1000

housing:
  units_per_project: 100
  cost: 100000
  duration_ticks: 5

power:
  capacity_per_project: 200
  cost: 150000
  duration_ticks: 8

repair:
  cost_per_infrastructure_point: 2000

loan:
  minimum_amount: 50000
  maximum_amount: 500000
  debt_limit: 1000000
  interest_per_tick_basis_points: 10
