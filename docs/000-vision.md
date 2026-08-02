# Sim Pilot Vision

**Status:** Accepted
**Version:** 1.1

---

# Vision

Sim Pilot enables players to interact with complex simulation games using natural language.

Instead of memorizing controls, navigating deep menus, or performing repetitive tasks, players describe their intent and the system executes the required game actions while respecting user-defined constraints.

The player controls goals, constraints, spending, approvals, and delegated authority. Sim Pilot
may teach the game, recommend objectives, and select objectives only inside authority the player
has explicitly delegated.

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

The AI supports rather than replaces the player. It has three separately governed roles:

- **Teacher:** answer questions and explain mechanics from observed state and versioned knowledge.
- **Advisor:** recommend evidence-grounded objectives without executing them.
- **Operator:** perform only explicitly delegated, proven actions within player constraints.

The player need not arrive with expert tactics. Sim Pilot may propose an objective, but it may not
turn a question or recommendation into game input.

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

After validation, OpenTTD, Rail Route, and Software Inc. supplied bounded production-integration
evidence. None is the active default roadmap target. Software Inc. is frozen as reference
capability because its technically rich workflows create too much product complexity before the
first satisfying player result.

The Software Inc. checkpoint preserves reusable safety and product boundaries:

- a read-only semantic bridge;
- fresh screenshot-derived visible targets;
- one gesture per cycle followed by re-observation;
- independent, default-no economic approvals;
- bounded time progression that returns the game to pause;
- durable workflow identity and fail-closed recovery;
- teaching and recommendations that cannot silently become mutation authority.

Game-specific Software Inc. assumptions and live evidence remain local to that adapter. They are
not proof for a future game, and the Software Inc. roadmap does not continue to another prompt by
default.

The next integration must be chosen before implementation. Selection starts with a Mac game the
player actually wants to play and one obvious, short terminal-first loop: observe fresh state,
accept a plain-English objective, perform one visible gesture, and independently verify the result.
Only after that loop is valuable and technically verifiable should Sim Pilot add a separate adapter
or any in-play interface. No successor game is selected by this vision revision.

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
- useful orientation before the player understands the game
- evidence-grounded recommendations without implicit execution
- reduced repetitive actions
- transparent execution
- predictable behavior
- reliable completion of delegated tasks

---

# Guiding Principles

- Players control goals, constraints, and authority.
- Sim Pilot may explain and recommend without receiving mutation authority.
- Objective selection requires explicit delegated authority.
- The runtime determines execution.
- Every action is observable.
- Every decision is explainable.
- Every task is bounded by explicit constraints.
- The player remains in control.
