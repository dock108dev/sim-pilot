"""OpenAI Responses API implementation of the Intent Compiler provider."""

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from sim_pilot.intent_compiler.errors import (
    CompilerProviderError,
    InvalidCompilerOutputError,
)
from sim_pilot.intent_compiler.models import (
    CompilerProviderResult,
    CompilerResponse,
)
from sim_pilot.intent_compiler.prompt import INTENT_COMPILER_PROMPT
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage


class OpenAICompilerProvider:
    """Request native Pydantic structured output; never parse prose."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        prompt: str = INTENT_COMPILER_PROMPT,
        max_retries: int | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("compiler model must not be empty")
        if max_retries is not None and max_retries < 0:
            raise ValueError("compiler retries must be non-negative")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("compiler output token limit must be positive")
        self._model = model
        self._prompt = prompt
        self._max_output_tokens = max_output_tokens
        try:
            self._client = (
                AsyncOpenAI(api_key=api_key)
                if max_retries is None
                else AsyncOpenAI(api_key=api_key, max_retries=max_retries)
            )
        except OpenAIError as error:
            raise CompilerProviderError(f"OpenAI compiler configuration failed: {error}") from error

    async def compile(self, instruction: str) -> CompilerProviderResult:
        if not instruction.strip():
            raise ValueError("instruction must not be empty")
        try:
            if self._max_output_tokens is None:
                response = await self._client.responses.parse(
                    model=self._model,
                    input=[
                        {"role": "developer", "content": self._prompt},
                        {"role": "user", "content": instruction},
                    ],
                    text_format=CompilerResponse,
                )
            else:
                response = await self._client.responses.parse(
                    model=self._model,
                    input=[
                        {"role": "developer", "content": self._prompt},
                        {"role": "user", "content": instruction},
                    ],
                    text_format=CompilerResponse,
                    max_output_tokens=self._max_output_tokens,
                )
        except OpenAIError as error:
            raise CompilerProviderError(f"OpenAI compiler request failed: {error}") from error
        except ValidationError as error:
            raise InvalidCompilerOutputError(
                f"OpenAI compiler output failed schema validation: {error}"
            ) from error
        parsed = response.output_parsed
        if parsed is None:
            raise InvalidCompilerOutputError(
                "OpenAI response contained no structured compiler output"
            )
        usage = response.usage
        token_usage = (
            None
            if usage is None
            else ProviderTokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
        )
        return CompilerProviderResult(
            response=parsed,
            metadata=ProviderMetadata(
                provider="openai",
                model=self._model,
                token_usage=token_usage,
            ),
        )
