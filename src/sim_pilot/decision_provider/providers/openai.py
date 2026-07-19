"""OpenAI Responses API implementation of runtime decision selection."""

from time import perf_counter
from typing import Protocol, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)
from pydantic import ValidationError

from sim_pilot.decision_provider.prompt import DECISION_PROMPT, PROMPT_VERSION
from sim_pilot.domain import Decision
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
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
from sim_pilot.runtime.decision_validation import validate_provider_decision


class _Usage(Protocol):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class _Response(Protocol):
    output_parsed: Decision | None
    output: list[object]
    usage: _Usage | None
    _request_id: str | None


class _Responses(Protocol):
    async def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[Decision],
        max_output_tokens: int | None = None,
    ) -> _Response: ...


class _Client(Protocol):
    @property
    def responses(self) -> _Responses: ...


class OpenAIDecisionProvider:
    """Select and validate one structured decision with explicit transient retries."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        transient_retries: int = 1,
        api_key: str | None = None,
        client: object | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("decision model must not be empty")
        if timeout_seconds <= 0 or transient_retries < 0:
            raise ValueError("decision timeout must be positive and retries non-negative")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("decision output token limit must be positive")
        self._model = model
        self._transient_retries = transient_retries
        self._max_output_tokens = max_output_tokens
        if client is not None:
            self._client = cast("_Client", client)
            return
        try:
            self._client = cast(
                "_Client",
                AsyncOpenAI(
                    api_key=api_key,
                    timeout=timeout_seconds,
                    max_retries=0,
                ),
            )
        except OpenAIError as error:
            raise DecisionAuthenticationError(
                f"OpenAI decision provider configuration failed: {error}"
            ) from error

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        started = perf_counter()
        response: _Response | None = None
        for attempt in range(self._transient_retries + 1):
            try:
                input_items = [
                    {"role": "developer", "content": DECISION_PROMPT},
                    {"role": "user", "content": context.canonical_json()},
                ]
                if self._max_output_tokens is None:
                    response = await self._client.responses.parse(
                        model=self._model,
                        input=input_items,
                        text_format=Decision,
                    )
                else:
                    response = await self._client.responses.parse(
                        model=self._model,
                        input=input_items,
                        text_format=Decision,
                        max_output_tokens=self._max_output_tokens,
                    )
                break
            except AuthenticationError as error:
                raise DecisionAuthenticationError(
                    f"OpenAI decision authentication failed: {error}"
                ) from error
            except APITimeoutError as error:
                if attempt >= self._transient_retries:
                    raise DecisionTimeoutError("OpenAI decision request timed out") from error
            except RateLimitError as error:
                if attempt >= self._transient_retries:
                    raise DecisionRateLimitError(
                        "OpenAI decision request was rate limited"
                    ) from error
            except APIConnectionError as error:
                if attempt >= self._transient_retries:
                    raise DecisionProviderUnavailableError(
                        "OpenAI decision provider is unavailable"
                    ) from error
            except APIStatusError as error:
                if error.status_code >= 500 and attempt < self._transient_retries:
                    continue
                raise DecisionProviderUnavailableError(
                    f"OpenAI decision request failed with status {error.status_code}"
                ) from error
            except ValidationError as error:
                raise MalformedDecisionOutputError(
                    f"OpenAI decision output failed schema validation: {error}"
                ) from error
            except OpenAIError as error:
                raise DecisionProviderUnavailableError(
                    f"OpenAI decision request failed: {error}"
                ) from error
        if response is None:
            raise DecisionProviderUnavailableError("OpenAI decision provider returned no response")
        decision = response.output_parsed
        if decision is None:
            refusal = self._refusal(response.output)
            if refusal is not None:
                raise DecisionRefusalError(f"OpenAI decision provider refused: {refusal}")
            raise EmptyDecisionResponseError(
                "OpenAI response contained no structured decision output"
            )
        try:
            validate_provider_decision(decision, context)
        except DecisionSemanticValidationError:
            raise
        usage = response.usage
        metadata = ProviderMetadata(
            provider="openai",
            model=self._model,
            request_id=self._request_identifier(response),
            token_usage=(
                None
                if usage is None
                else ProviderTokenUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )
            ),
            latency_ms=(perf_counter() - started) * 1000,
            prompt_version=PROMPT_VERSION,
            validation_result="valid",
        )
        return DecisionProviderResult(decision=decision, metadata=metadata)

    @staticmethod
    def _refusal(output: list[object]) -> str | None:
        for item in output:
            content = getattr(item, "content", ())
            if not isinstance(content, (list, tuple)):
                continue
            for part in cast("list[object] | tuple[object, ...]", content):
                refusal = getattr(part, "refusal", None)
                if isinstance(refusal, str) and refusal:
                    return refusal
        return None

    @staticmethod
    def _request_identifier(response: object) -> str | None:
        request_id = getattr(response, "_request_id", None)
        return request_id if isinstance(request_id, str) else None
