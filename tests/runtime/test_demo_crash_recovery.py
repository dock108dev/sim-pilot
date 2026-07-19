"""Regression coverage for the documented process-level crash demonstration."""

import asyncio

import pytest

from scripts.demo_crash_recovery import main


def test_crash_recovery_demo_uses_application_reconciliation_composition(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(main())
    output = capsys.readouterr().out

    assert "classification=definitely_executed" in output
    assert "resolved=True" in output
    assert "tick=1" in output
