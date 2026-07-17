"""Provider-independent Intent Compiler pipeline tests."""

import asyncio
from types import SimpleNamespace

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
        assert result.report.prompt_version == "intent-compiler-v2"
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


def test_openai_provider_returns_model_and_token_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_response = response(valid_specification())

    class FakeResponses:
        async def parse(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["model"] == "test-model"
            return SimpleNamespace(
                output_parsed=expected_response,
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=30,
                    total_tokens=150,
                ),
            )

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str | None = None) -> None:
            del api_key
            self.responses = FakeResponses()

    monkeypatch.setattr(
        "sim_pilot.intent_compiler.providers.openai.AsyncOpenAI",
        FakeAsyncOpenAI,
    )

    async def scenario() -> None:
        result = await OpenAICompilerProvider(model="test-model", api_key="test-key").compile(
            "Reach one million cash."
        )
        assert result.response == expected_response
        assert result.metadata.provider == "openai"
        assert result.metadata.model == "test-model"
        assert result.metadata.token_usage is not None
        assert result.metadata.token_usage.total_tokens == 150

    asyncio.run(scenario())
