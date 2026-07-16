# ADR-002: uv for Python Project Management

- Status: Accepted
- Date: 2026-07-16

## Context

Local development and CI need the same Python version, dependency resolution, environment setup,
and command execution without relying on a machine-specific `python` launcher.

## Decision

Use uv to manage Python, dependencies, the virtual environment, lockfile, builds, and project
commands. Commit `uv.lock` and use locked synchronization in CI.

## Consequences

Developers use `uv sync --dev` and `uv run ...`. Dependency changes must refresh the lockfile. uv
is the only additional bootstrap tool required beyond Git.
