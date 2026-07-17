"""Opt-in live structured-output provider validation."""

import asyncio
import os

import pytest

from sim_pilot.config import compiler_model
from sim_pilot.domain import ObjectiveType
from sim_pilot.intent_compiler import IntentCompiler, ValidationStatus
from sim_pilot.intent_compiler.providers import OpenAICompilerProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SIM_PILOT_LIVE_COMPILER") != "1" or not os.getenv("OPENAI_API_KEY"),
        reason="set SIM_PILOT_LIVE_COMPILER=1 and OPENAI_API_KEY to run live compiler tests",
    ),
]


def test_live_openai_structured_compilation() -> None:
    async def scenario() -> None:
        compiler = IntentCompiler(OpenAICompilerProvider(model=compiler_model()))
        result = await compiler.compile(
            "Run until cash reaches $1 million. Do not take loans. Keep at least $100,000 "
            "available. Ask before spending more than $50,000."
        )
        assert result.report.validation_status is ValidationStatus.VALID
        assert result.specification is not None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("instruction", "objective_type"),
    (
        ("Reach $750,000 cash.", ObjectiveType.REACH_RESOURCE),
        ("Maintain infrastructure above 60 percent.", ObjectiveType.MAINTAIN_RESOURCE),
        ("Complete the active power project.", ObjectiveType.COMPLETE_PROJECT),
        ("Run until population reaches 1,000.", ObjectiveType.RUN_UNTIL),
    ),
)
def test_live_openai_supports_every_objective(
    instruction: str, objective_type: ObjectiveType
) -> None:
    async def scenario() -> None:
        result = await IntentCompiler(OpenAICompilerProvider(model=compiler_model())).compile(
            instruction
        )
        assert result.report.validation_status is ValidationStatus.VALID
        assert result.specification is not None
        assert result.specification.objective.type is objective_type

    asyncio.run(scenario())


def test_live_openai_requests_clarification_for_missing_threshold() -> None:
    async def scenario() -> None:
        result = await IntentCompiler(OpenAICompilerProvider(model=compiler_model())).compile(
            "Keep enough cash available."
        )
        assert result.report.validation_status is ValidationStatus.CLARIFICATION_REQUIRED
        assert result.specification is None
        assert result.report.ambiguities

    asyncio.run(scenario())
