"""Explicitly gated one-call Codex CLI decision smoke test."""

import asyncio
import os

import pytest

from sim_pilot.config import codex_model
from sim_pilot.decision_provider import CodexCLIDecisionProvider
from tests.decision_provider.helpers import make_context

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SIM_PILOT_LIVE_CODEX") != "1"
        or os.getenv("SIM_PILOT_LIVE_CODEX_DECISION") != "1",
        reason="set SIM_PILOT_LIVE_CODEX=1 and SIM_PILOT_LIVE_CODEX_DECISION=1",
    ),
]


def test_live_codex_decision_smoke() -> None:
    result = asyncio.run(CodexCLIDecisionProvider(model=codex_model()).decide(make_context()))
    assert result.metadata.provider == "codex"
