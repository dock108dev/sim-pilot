"""Explicitly gated one-call Codex CLI compiler smoke test."""

import asyncio
import os

import pytest

from sim_pilot.config import codex_model
from sim_pilot.intent_compiler import IntentCompiler
from sim_pilot.intent_compiler.providers import CodexCLICompilerProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SIM_PILOT_LIVE_CODEX") != "1"
        or os.getenv("SIM_PILOT_LIVE_CODEX_COMPILER") != "1",
        reason="set SIM_PILOT_LIVE_CODEX=1 and SIM_PILOT_LIVE_CODEX_COMPILER=1",
    ),
]


def test_live_codex_compiler_smoke() -> None:
    result = asyncio.run(
        IntentCompiler(CodexCLICompilerProvider(model=codex_model())).compile(
            "Reach one million cash without taking loans."
        )
    )
    assert result.report.prompt_version
