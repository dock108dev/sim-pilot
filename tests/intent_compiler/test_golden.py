"""Golden natural-language-to-structured-output examples."""

import asyncio
import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from sim_pilot.intent_compiler import CompilerResponse, IntentCompiler, ValidationStatus
from sim_pilot.intent_compiler.providers import ScriptedCompilerProvider


class GoldenCase(TypedDict):
    instruction: str
    response: object
    status: str


FIXTURE = Path(__file__).parents[1] / "fixtures" / "compiler_golden.json"
CASES = cast("list[GoldenCase]", json.loads(FIXTURE.read_text()))


@pytest.mark.parametrize("case", CASES, ids=lambda case: cast("GoldenCase", case)["instruction"])
def test_golden_compilation(case: GoldenCase) -> None:
    async def scenario() -> None:
        provider_response = CompilerResponse.model_validate_json(json.dumps(case["response"]))
        result = await IntentCompiler(ScriptedCompilerProvider([provider_response])).compile(
            case["instruction"]
        )
        assert result.report.validation_status is ValidationStatus(case["status"])
        if result.report.validation_status is ValidationStatus.VALID:
            assert result.specification == provider_response.specification
        else:
            assert result.specification is None

    asyncio.run(scenario())


def test_golden_suite_has_at_least_twenty_examples() -> None:
    assert len(CASES) >= 20
