# Sim Pilot Engineering Instructions

## Project Objective

Build a local runtime that converts natural-language objectives into validated actions against a deterministic reference simulation.

The runtime executes one action per cycle:

1. Observe state
2. Evaluate task progress
3. Select one action
4. Validate the action
5. Execute the action
6. Observe the resulting state
7. Verify the effect
8. Continue, complete, request approval, or report blocked

## Source Documents

Implementation must follow:

- `docs/000-vision.md`
- `docs/001-month-1-design.md`
- `docs/002-reference-simulation.md`

When the documents conflict, stop and report the conflict rather than selecting an interpretation silently.

## Technology

- Python 3.12
- `uv`
- Pydantic v2
- SQLite
- Typer
- pytest
- Ruff
- Pyright

## Engineering Rules

- Use typed domain models.
- Execute one action per runtime cycle.
- Treat model output as untrusted structured data.
- Validate every action deterministically before execution.
- Verify state after every executed action.
- Persist task lifecycle events in sequence.
- Keep the reference simulation deterministic when supplied a seed.
- Keep provider-specific LLM code behind one interface.
- Add tests with each implementation change.
- Use scripted decision providers for automated tests.
- Do not require paid model calls in CI.

## Working Method

For each assigned milestone:

1. Read the relevant design documents.
2. Inspect the current repository.
3. Produce a brief implementation plan.
4. Implement the smallest complete vertical slice.
5. Run formatting, type checks, and tests.
6. Report completed work, changed files, test results, and unresolved questions.

## Definition of Done

A change is complete when:

- implementation matches the documented contract
- tests cover the expected and failure paths
- Ruff passes
- Pyright passes
- pytest passes
- documentation is updated when an interface changes