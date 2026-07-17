"""OpenAI decision provider behavior using a fake Responses client."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
from pydantic import ValidationError

from sim_pilot.decision_provider.providers.openai import OpenAIDecisionProvider
from sim_pilot.domain import Action, Decision, DecisionType
from sim_pilot.runtime.decision_errors import (
    DecisionAuthenticationError,
    DecisionProviderUnavailableError,
    DecisionRateLimitError,
    DecisionRefusalError,
    DecisionSemanticValidationError,
    DecisionTimeoutError,
    EmptyDecisionResponseError,
    MalformedDecisionOutputError,
)
from tests.decision_provider.helpers import make_context


@dataclass
class FakeUsage:
    input_tokens: int = 120
    output_tokens: int = 30
    total_tokens: int = 150


class FakeResponse:
    def __init__(
        self,
        decision: Decision | None,
        *,
        output: list[object] | None = None,
    ) -> None:
        self.output_parsed = decision
        self.output = output or []
        self.usage: FakeUsage | None = FakeUsage()
        self._request_id: str | None = "req_test"


class FakeResponses:
    def __init__(self, outcomes: list[FakeResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[Decision],
    ) -> FakeResponse:
        assert model == "test-model"
        assert text_format is Decision
        assert input[0]["role"] == "developer"
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[FakeResponse | Exception]) -> None:
        self._responses = FakeResponses(outcomes)

    @property
    def responses(self) -> FakeResponses:
        return self._responses


def _decision(action_type: str = "advance_time") -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason="Advance one tick.",
        action=Action(
            type=action_type,
            parameters={"ticks": 1},
            expected_effect="Advance one tick.",
        ),
    )


def _provider(client: FakeClient, *, retries: int = 1) -> OpenAIDecisionProvider:
    return OpenAIDecisionProvider(
        model="test-model",
        timeout_seconds=5,
        transient_retries=retries,
        client=client,
    )


def test_structured_decision_and_metadata_are_returned() -> None:
    async def scenario() -> None:
        client = FakeClient([FakeResponse(_decision())])
        result = await _provider(client).decide(make_context())
        assert result.decision == _decision()
        assert result.metadata.provider == "openai"
        assert result.metadata.model == "test-model"
        assert result.metadata.request_id == "req_test"
        assert result.metadata.prompt_version == "decision-provider-v1"
        assert result.metadata.validation_result == "valid"
        assert result.metadata.token_usage is not None
        assert result.metadata.token_usage.total_tokens == 150
        assert result.metadata.latency_ms is not None
        assert client.responses.calls == 1

    asyncio.run(scenario())


def test_transient_timeout_retries_once_then_succeeds() -> None:
    async def scenario() -> None:
        timeout = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
        client = FakeClient([timeout, FakeResponse(_decision())])
        result = await _provider(client).decide(make_context())
        assert result.decision == _decision()
        assert client.responses.calls == 2

    asyncio.run(scenario())


def test_persistent_timeout_is_typed() -> None:
    async def scenario() -> None:
        outcomes: list[FakeResponse | Exception] = [
            APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
            APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
        ]
        with pytest.raises(DecisionTimeoutError):
            await _provider(FakeClient(outcomes)).decide(make_context())

    asyncio.run(scenario())


def test_authentication_failure_is_typed_and_not_retried() -> None:
    async def scenario() -> None:
        response = httpx.Response(
            401,
            request=httpx.Request("POST", "https://api.openai.com"),
        )
        error = AuthenticationError("invalid key", response=response, body=None)
        client = FakeClient([error])
        with pytest.raises(DecisionAuthenticationError):
            await _provider(client).decide(make_context())
        assert client.responses.calls == 1

    asyncio.run(scenario())


def test_refusal_and_semantic_invalidity_are_typed_without_retry() -> None:
    async def scenario() -> None:
        refusal_part = SimpleNamespace(refusal="Cannot select a decision.")
        refusal_output = SimpleNamespace(content=[refusal_part])
        refusal_client = FakeClient([FakeResponse(None, output=[refusal_output])])
        with pytest.raises(DecisionRefusalError):
            await _provider(refusal_client).decide(make_context())
        invalid_client = FakeClient([FakeResponse(_decision("invent_train"))])
        with pytest.raises(DecisionSemanticValidationError, match="not advertised"):
            await _provider(invalid_client).decide(make_context())
        assert invalid_client.responses.calls == 1

    asyncio.run(scenario())


def test_rate_limit_connection_malformed_and_empty_failures_are_typed() -> None:
    async def scenario() -> None:
        response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com"),
        )
        rate_error = RateLimitError("limited", response=response, body=None)
        with pytest.raises(DecisionRateLimitError):
            await _provider(FakeClient([rate_error]), retries=0).decide(make_context())

        connection_error = APIConnectionError(
            message="offline",
            request=httpx.Request("POST", "https://api.openai.com"),
        )
        with pytest.raises(DecisionProviderUnavailableError):
            await _provider(FakeClient([connection_error]), retries=0).decide(make_context())

        try:
            Decision.model_validate({})
        except ValidationError as malformed:
            with pytest.raises(MalformedDecisionOutputError):
                await _provider(FakeClient([malformed]), retries=0).decide(make_context())

        with pytest.raises(EmptyDecisionResponseError):
            await _provider(FakeClient([FakeResponse(None)]), retries=0).decide(make_context())

    asyncio.run(scenario())


def test_provider_configuration_does_not_log_or_require_key_with_fake_client() -> None:
    client = FakeClient([FakeResponse(_decision())])
    provider = OpenAIDecisionProvider(
        model="test-model",
        timeout_seconds=5,
        api_key=cast("str", "not-recorded"),
        client=client,
    )
    assert provider is not None
