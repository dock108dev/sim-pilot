# Sim Pilot Vision

**Status:** Draft
**Version:** 0.1

---

# Vision

Sim Pilot enables players to interact with complex simulation games using natural language.

Instead of memorizing controls, navigating deep menus, or performing repetitive tasks, players describe their intent and the system executes the required game actions while respecting user-defined constraints.

The player remains in control of strategy and decision making.

Sim Pilot reduces execution complexity.

---

# Problem Statement

Modern simulation games provide enormous depth but often require significant effort to interact with their systems.

Players frequently spend more time navigating interfaces than making meaningful decisions.

Examples include:

- Navigating nested menus
- Remembering dozens of keyboard shortcuts
- Repeating routine maintenance
- Waiting for long-running objectives
- Managing administrative tasks instead of strategic decisions

These activities create friction without adding meaningful gameplay.

---

# Product Vision

Provide an intelligent copilot capable of translating player intent into game actions.

Example:

Instead of:

> Navigate five menus to adjust train schedules.

The player says:

> Increase passenger service between these two cities.

Instead of:

> Monitor cash until enough money exists to build a new station.

The player says:

> Build the station once we reach $1 million and notify me when it's complete.

Instead of:

> Pause every few minutes to perform repetitive maintenance.

The player says:

> Keep the network running efficiently while I plan expansion.

---

# Design Principles

## Player First

The AI supports the player.

It does not replace the player.

The player defines objectives.

The AI performs delegated work.

---

## Natural Language

Interaction should feel conversational.

Players should describe goals rather than individual inputs.

---

## Transparent Execution

The system should always be able to explain:

- current objective
- current activity
- completed work
- reason for major decisions
- reason for stopping

---

## Bounded Authority

The player defines operational limits.

Examples:

- maximum spending
- forbidden actions
- notification conditions
- approval thresholds

The AI operates only within those limits.

---

## Incremental Delegation

Players should choose how much authority to grant.

Examples:

### Direct Control

> Buy another train.

### Assisted

> Find the best train for this route.

### Delegated

> Maintain this route until it reaches profitability.

---

## Reusable Runtime

The core runtime should remain independent of any individual game.

Game-specific behavior is isolated behind a common adapter interface.

---

# Initial Product Scope

The first implementation validates the runtime using a deterministic reference simulation.

After validation, the first production adapter targets OpenTTD.

OpenTTD provides an ideal validation environment because it combines:

- economic simulation
- transportation planning
- long-running objectives
- deterministic mechanics
- meaningful delegated tasks

---

# Long-Term Direction

The runtime should support additional simulation games through adapter implementations.

Potential future adapters include:

- Oxygen Not Included
- Football Manager
- Cities: Skylines
- Microsoft Flight Simulator
- Train Sim World
- American Truck Simulator

Each adapter exposes the same runtime interface while translating runtime actions into game-specific behavior.

---

# Example User Scenarios

## Transportation

> Connect these two cities using trains.

---

## Operations

> Keep this company profitable until cash reaches $2 million.

---

## Maintenance

> Replace unreliable vehicles as needed.

---

## Monitoring

> Pause if operating profit becomes negative.

---

## Planning

> Show me the three biggest bottlenecks in my network.

---

## Notification

> Let me know when construction finishes.

---

# Success Criteria

The product succeeds when a player can describe objectives naturally and trust the system to execute routine work correctly within defined constraints.

Success is measured by:

- reduced interaction complexity
- reduced repetitive actions
- transparent execution
- predictable behavior
- reliable completion of delegated tasks

---

# Guiding Principles

- Players define intent.
- The runtime determines execution.
- Every action is observable.
- Every decision is explainable.
- Every task is bounded by explicit constraints.
- The player remains in control.
