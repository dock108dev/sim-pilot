# Sim Pilot

Sim Pilot is a local runtime for translating natural-language objectives into validated actions
against deterministic simulations. This repository currently contains the Month 1 project
foundation and typed domain models; the runtime engine, LLM integration, persistence, and
simulation behavior are intentionally not implemented yet.

Every serialized domain model carries `schema_version`, currently `1`. Changes to
`TaskSpecification`, `Observation`, `Action`, or `Decision` require an accompanying RFC update.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12 (uv can install and manage it automatically)

The project does not depend on a `python` command being available. Use `uv run` for project
commands. On machines that expose Python through `py`, the equivalent direct interpreter command
is `py -3.12`, but it is not needed for the setup below.

## Local setup

```bash
uv python install 3.12
uv sync --dev
```

## Validation

Run the same checks used by GitHub Actions:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

To apply formatting locally:

```bash
uv run ruff format .
```

## Package layout

The public Python package is `sim_pilot`. Domain models are exported from `sim_pilot.domain` and
the package root. The `runtime`, `adapters`, `llm`, `persistence`, and `logging` subpackages are
foundation boundaries only; their behavior belongs to later milestones.

Dependency direction is `CLI -> Runtime -> Domain <- Adapter`. Adapters may import domain types,
but must not import runtime modules.
