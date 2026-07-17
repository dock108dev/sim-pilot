"""OpenAI Responses API implementation of the Intent Compiler provider."""

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from sim_pilot.intent_compiler.errors import (
    CompilerProviderError,
    InvalidCompilerOutputError,
)
from sim_pilot.intent_compiler.models import (
    CompilerProviderMetadata,
    CompilerProviderResult,
    CompilerResponse,
    CompilerTokenUsage,
)
from sim_pilot.intent_compiler.prompt import INTENT_COMPILER_PROMPT


class OpenAICompilerProvider:
    """Request native Pydantic structured output; never parse prose."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("compiler model must not be empty")
        self._model = model
        try:
            self._client = AsyncOpenAI(api_key=api_key)
        except OpenAIError as error:
            raise CompilerProviderError(f"OpenAI compiler configuration failed: {error}") from error

    async def compile(self, instruction: str) -> CompilerProviderResult:
        if not instruction.strip():
            raise ValueError("instruction must not be empty")
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "developer", "content": INTENT_COMPILER_PROMPT},
                    {"role": "user", "content": instruction},
                ],
                text_format=CompilerResponse,
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
            else CompilerTokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
        )
        return CompilerProviderResult(
            response=parsed,
            metadata=CompilerProviderMetadata(
                provider="openai",
                model=self._model,
                token_usage=token_usage,
            ),
        )
