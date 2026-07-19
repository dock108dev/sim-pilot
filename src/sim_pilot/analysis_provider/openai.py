"""Schema-bound OpenAI providers for analysis compilation and explanation."""

from __future__ import annotations

import json

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from sim_pilot.analysis.compiler import AnalysisCompilation
from sim_pilot.analysis.contracts import AnalysisExplanation
from sim_pilot.analysis.explanation import ExplanationInput
from sim_pilot.analysis.prompt import ANALYSIS_COMPILER_PROMPT, ANALYSIS_EXPLANATION_PROMPT
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage


class _OpenAIProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        max_retries: int,
        max_output_tokens: int,
    ) -> None:
        if not model.strip():
            raise ValueError("analysis model must not be empty")
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, max_retries=max_retries)
        self._max_output_tokens = max_output_tokens
        self.last_metadata: ProviderMetadata | None = None

    async def _parse(self, *, developer: str, user: str, output_type: type[BaseModel]):
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "developer", "content": developer},
                    {"role": "user", "content": user},
                ],
                text_format=output_type,
                max_output_tokens=self._max_output_tokens,
            )
        except OpenAIError as error:
            raise RuntimeError(f"OpenAI analysis request failed: {error}") from error
        if response.output_parsed is None:
            raise RuntimeError("OpenAI analysis response contained no structured output")
        usage = response.usage
        self.last_metadata = ProviderMetadata(
            provider="openai",
            model=self._model,
            token_usage=(
                None
                if usage is None
                else ProviderTokenUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )
            ),
        )
        return response.output_parsed


class OpenAIAnalysisCompiler(_OpenAIProvider):
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        max_retries: int = 2,
        max_output_tokens: int = 1_000,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            max_retries=max_retries,
            max_output_tokens=max_output_tokens,
        )

    async def compile(self, question: str) -> AnalysisCompilation:
        result = await self._parse(
            developer=ANALYSIS_COMPILER_PROMPT,
            user=question,
            output_type=AnalysisCompilation,
        )
        assert isinstance(result, AnalysisCompilation)
        return result


class OpenAIExplanationProvider(_OpenAIProvider):
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        max_retries: int = 2,
        max_output_tokens: int = 2_000,
        maximum_prompt_bytes: int = 64_000,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            max_retries=max_retries,
            max_output_tokens=max_output_tokens,
        )
        self._maximum_prompt_bytes = maximum_prompt_bytes

    async def explain(self, context: ExplanationInput) -> AnalysisExplanation:
        payload = json.dumps(context.model_dump(mode="json"), separators=(",", ":"))
        if len(payload.encode()) > self._maximum_prompt_bytes:
            raise RuntimeError("analysis explanation input exceeds the configured byte limit")
        result = await self._parse(
            developer=ANALYSIS_EXPLANATION_PROMPT,
            user=payload,
            output_type=AnalysisExplanation,
        )
        assert isinstance(result, AnalysisExplanation)
        return result
