# ADR-001: Python 3.12

- Status: Accepted
- Date: 2026-07-16

## Context

Sim Pilot needs a typed, testable local runtime with strong library support for validation,
SQLite, command-line tools, and future provider integrations.

## Decision

Use Python 3.12 for the runtime and require `>=3.12,<3.13` in project metadata. Use modern typing
syntax and run Pyright in strict mode.

## Consequences

The project gets a mature standard library and ecosystem while keeping one supported interpreter
line during Month 1. Supporting another Python version requires an explicit compatibility decision
and CI coverage.
