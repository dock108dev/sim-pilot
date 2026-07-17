"""Provider-independent Intent Compiler pipeline tests."""

import asyncio

import pytest
from pydantic import ValidationError

from sim_pilot.intent_compiler import (
    CompilerProviderError,
    CompilerResponse,
    IntentCompiler,
    ValidationStatus,
)
from sim_pilot.intent_compiler.providers import OpenAICompilerProvider, ScriptedCompilerProvider
from tests.intent_compiler.helpers import response, valid_specification


def test_valid_compilation_reports_prompt_assumptions_and_warnings() -> None:
    async def scenario() -> None:
        provider = ScriptedCompilerProvider(
            [
                response(
                    valid_specification(),
                    assumptions=("Cash means the simulation cash resource.",),
                    warnings=("The target may require many ticks.",),
                )
            ]
        )
        result = await IntentCompiler(provider).compile("Reach one million cash.")
        assert result.report.validation_status is ValidationStatus.VALID
        assert result.report.prompt_version == "intent-compiler-v1"
        assert result.specification == valid_specification()
        assert provider.request_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_response", "status"),
    (
        (
            response(ambiguities=("Minimum reserve amount was not specified.",)),
            ValidationStatus.CLARIFICATION_REQUIRED,
        ),
        (
            response(unsupported_requests=("Winning the game is unsupported.",)),
            ValidationStatus.UNSUPPORTED,
        ),
        (response(), ValidationStatus.INVALID),
    ),
)
def test_non_executable_compilations_never_expose_specification(
    provider_response: CompilerResponse, status: ValidationStatus
) -> None:
    async def scenario() -> None:
        result = await IntentCompiler(ScriptedCompilerProvider([provider_response])).compile(
            "Instruction"
        )
        assert result.report.validation_status is status
        assert result.specification is None

    asyncio.run(scenario())


def test_structured_output_rejects_missing_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CompilerResponse.model_validate({"specification": None})
    with pytest.raises(ValidationError):
        CompilerResponse.model_validate(
            {
                "specification": None,
                "assumptions": (),
                "warnings": (),
                "unsupported_requests": (),
                "ambiguities": (),
                "prose": "not allowed",
            }
        )


def test_empty_instruction_and_provider_failure_are_typed() -> None:
    async def scenario() -> None:
        compiler = IntentCompiler(ScriptedCompilerProvider([]))
        with pytest.raises(ValueError, match="must not be empty"):
            await compiler.compile("  ")
        with pytest.raises(CompilerProviderError, match="exhausted"):
            await compiler.compile("Reach cash.")

    asyncio.run(scenario())


def test_openai_provider_configuration_failure_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CompilerProviderError, match="configuration failed"):
        OpenAICompilerProvider(model="test-model")
